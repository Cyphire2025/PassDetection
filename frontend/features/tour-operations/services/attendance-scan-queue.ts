import { operationsApi, type AttendanceScanResponse } from "@/features/operations/api/operations.api";
import { useAuthStore } from "@/stores/auth.store";
import { writeAttendanceSessionProgress } from "./attendance-session-progress";
import {
  attendanceQueueRowId,
  createAttendanceScanReference,
  createRejectedAttendanceScan,
  isAttendanceScanReference,
  sanitizeLegacyRejectedAttendanceScan,
} from "./attendance-queue-privacy";
import {
  attendanceRetryState,
  classifyAttendanceCloseoutQueue,
  earliestAttendanceAttemptAt,
  isAttendanceAttemptEligible,
  type AttendanceCloseoutQueueCounts,
} from "./attendance-retry-policy";
import {
  hasUnsafeBrowserAttendanceQueue,
  type AttendanceQueueLogoutDisposition,
  type BrowserAttendanceQueueSafetySnapshot,
} from "./attendance-queue-safety-contract";
import {
  isPermanentAttendanceScanError,
  isRecoverableAttendanceScanError,
  isSuccessfulAttendanceReplayStatus,
  type AttendanceSyncUpdate,
} from "./attendance-sync-policy";

export interface AttendanceScanInput {
  groupId: string;
  sessionId: string;
  qrPayload: string;
  clientEventId: string;
  scannedAt: string;
  deviceId: string;
}

export interface PendingAttendanceScan extends Omit<AttendanceScanInput, "groupId"> {
  // Optional only for records written before group-scoped queue version 3.
  groupId?: string;
  id: string;
  scanReference: string;
  ownerUserId: string;
  queuedAt: string;
  attemptCount: number;
  nextAttemptAt: string;
  lastAttemptAt?: string;
  deliveryState: "pending" | "sending";
  deliveryStartedAt?: string;
}

export interface RejectedAttendanceScan {
  id: string;
  scanReference: string;
  ownerUserId: string;
  groupId?: string;
  sessionId: string;
  clientEventId: string;
  scannedAt: string;
  deviceId: string;
  queuedAt: string;
  rejectedAt: string;
  errorCode: string;
}

export interface AttendanceScanSyncResult {
  synced: number;
  failed: number;
  discarded: number;
  updates: AttendanceSyncUpdate[];
  nextAttemptAt: string | null;
}

export type AttendanceScanSyncUpdate = AttendanceSyncUpdate;

const DB_NAME = "passdetection-tour-ops";
const DB_VERSION = 4;
const PENDING_STORE_NAME = "pending-attendance-scans";
const REJECTED_STORE_NAME = "rejected-attendance-scans";
const OWNER_INDEX = "owner-user-id";
const SCHEDULE_EVENT = "passdetection:attendance-queue-schedule-changed";
const SCHEDULE_CHANNEL = "passdetection-attendance-queue-schedule";
const MIGRATION_LOCK = "passdetection-attendance-queue-v4-migration";
const OWNER_LOCK_PREFIX = "passdetection-attendance-owner";
const DRAIN_LOCK_PREFIX = "passdetection-attendance-drain";

let activeSync:
  | { ownerUserId: string; promise: Promise<AttendanceScanSyncResult> }
  | null = null;
let privacyMigrationPromise: Promise<void> | null = null;
const fallbackOwnerLanes = new Map<string, Promise<void>>();

export async function enqueueAttendanceScan(
  scan: AttendanceScanInput,
  retryError?: unknown,
) {
  const ownerUserId = requireCurrentUserId();
  return withOwnerQueueLock(ownerUserId, async () => {
    assertCurrentOwner(ownerUserId);
    const scanReference = await createAttendanceScanReference({
      ownerUserId,
      groupId: scan.groupId,
      sessionId: scan.sessionId,
      qrPayload: scan.qrPayload,
    });
    const id = attendanceQueueRowId(scanReference);
    const queuedAt = new Date().toISOString();
    const initialRetry = retryError
      ? attendanceRetryState({
          previousAttemptCount: 0,
          retryAfterMs: getRetryAfterMs(retryError),
        })
      : { attemptCount: 0, nextAttemptAt: queuedAt };
    const pendingScan: PendingAttendanceScan = {
      ...scan,
      id,
      scanReference,
      ownerUserId,
      queuedAt,
      ...initialRetry,
      deliveryState: "pending",
    };
    const db = await openDb();
    try {
      assertCurrentOwner(ownerUserId);
      const transaction = db.transaction(PENDING_STORE_NAME, "readwrite");
      const completion = transactionToPromise(transaction);
      const store = transaction.objectStore(PENDING_STORE_NAME);
      const existing = await requestToPromise<PendingAttendanceScan | undefined>(
        store.get(id),
      );
      if (!existing) await requestToPromise(store.put(pendingScan));
      await completion;
      announceScheduleChanged();
      return { pending: existing ?? pendingScan, duplicate: Boolean(existing) };
    } finally {
      db.close();
    }
  });
}

export async function countPendingAttendanceScans(groupId?: string) {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId) return 0;
  const scans = await listPendingForOwner(ownerUserId);
  if (!groupId) return scans.length;
  return scans.filter((scan) => !scan.groupId || scan.groupId === groupId).length;
}

export async function listPendingAttendanceScans() {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId) return [];
  return listPendingForOwner(ownerUserId);
}

export async function getNextPendingAttendanceAttemptAt() {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId) return null;
  const rows = await listPendingForOwner(ownerUserId);
  return earliestAttendanceAttemptAt(
    rows.filter((row) => row.deliveryState !== "sending"),
  );
}

export async function removePendingAttendanceScan(id: string) {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId) return;
  await withOwnerQueueLock(ownerUserId, async () => {
    await removePendingForOwner(id, ownerUserId);
    announceScheduleChanged();
  });
}

export async function countRejectedAttendanceScans(
  groupId: string | null,
  sessionId: string | null,
) {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId || !groupId || !sessionId) return 0;
  const scans = await listRejectedForOwner(ownerUserId);
  return scans.filter(
    (scan) => (!scan.groupId || scan.groupId === groupId)
      && scan.sessionId === sessionId,
  ).length;
}

export async function acknowledgeRejectedAttendanceScans(
  groupId: string | null,
  sessionId: string | null,
) {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId || !groupId || !sessionId) return 0;
  return withOwnerQueueLock(ownerUserId, async () => {
    assertCurrentOwner(ownerUserId);
    const db = await openDb();
    try {
      const transaction = db.transaction(REJECTED_STORE_NAME, "readwrite");
      const completion = transactionToPromise(transaction);
      const store = transaction.objectStore(REJECTED_STORE_NAME);
      const scans = await requestToPromise<RejectedAttendanceScan[]>(
        store.index(OWNER_INDEX).getAll(ownerUserId),
      );
      const matchingScans = scans.filter(
        (scan) => (!scan.groupId || scan.groupId === groupId)
          && scan.sessionId === sessionId,
      );
      for (const scan of matchingScans) store.delete(scan.id);
      await completion;
      announceScheduleChanged();
      return matchingScans.length;
    } finally {
      db.close();
    }
  });
}

export function syncPendingAttendanceScans(): Promise<AttendanceScanSyncResult> {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId) return Promise.resolve(emptySyncResult());
  if (activeSync?.ownerUserId === ownerUserId) return activeSync.promise;
  if (activeSync) {
    return activeSync.promise
      .catch(() => undefined)
      .then(() => syncPendingAttendanceScans());
  }
  if (!navigator.onLine) {
    return getNextPendingAttendanceAttemptAt().then((nextAttemptAt) => ({
      ...emptySyncResult(),
      nextAttemptAt,
    }));
  }

  const request = withBrowserLock(
    `${DRAIN_LOCK_PREFIX}:${ownerUserId}`,
    () => performPendingAttendanceScanSync(ownerUserId),
  ).finally(() => {
    if (activeSync?.promise === request) activeSync = null;
  });
  activeSync = { ownerUserId, promise: request };
  return request;
}

async function performPendingAttendanceScanSync(
  ownerUserId: string,
): Promise<AttendanceScanSyncResult> {
  if (getCurrentUserId() !== ownerUserId) return emptySyncResult();
  const scans = await withOwnerQueueLock(
    ownerUserId,
    () => listPendingForOwner(ownerUserId),
  );
  let synced = 0;
  let failed = 0;
  let discarded = 0;
  const updates: AttendanceScanSyncUpdate[] = [];

  for (const candidate of scans) {
    if (getCurrentUserId() !== ownerUserId || candidate.ownerUserId !== ownerUserId) break;
    if (!isAttendanceAttemptEligible(candidate.nextAttemptAt, candidate.queuedAt)) continue;
    const scan = await withOwnerQueueLock(
      ownerUserId,
      () => claimPendingAttendanceDelivery(candidate.id, ownerUserId),
    );
    if (!scan) continue;
    announceScheduleChanged();

    let response: AttendanceScanResponse;
    try {
      response = await operationsApi.scanMyAttendanceSession({
        sessionId: scan.sessionId,
        qrPayload: scan.qrPayload,
        clientEventId: scan.clientEventId,
        scannedAt: scan.scannedAt,
        deviceId: scan.deviceId,
        syncSource: "offline",
      });
    } catch (error) {
      const permanent = isPermanentAttendanceScanError(getErrorCode(error));
      try {
        await withOwnerQueueLock(ownerUserId, async () => {
          if (permanent) {
            await quarantineRejectedAttendanceScan(scan, getErrorCode(error), ownerUserId);
          } else {
            await markPendingAttendanceRetry(scan, error, ownerUserId);
          }
        });
      } catch (storageError) {
        await withOwnerQueueLock(
          ownerUserId,
          () => releasePendingAttendanceDelivery(scan.id, ownerUserId),
        ).catch(() => undefined);
        throw storageError;
      }
      announceScheduleChanged();
      if (permanent) {
        discarded += 1;
      } else {
        failed += 1;
        // A recoverable failure will usually affect every following row too.
        // Persist the exact eligible time and stop instead of fanning out.
        break;
      }
      continue;
    }

    try {
      await withOwnerQueueLock(ownerUserId, async () => {
        if (!isSuccessfulAttendanceReplayStatus(response.status)) {
          await quarantineRejectedAttendanceScan(
            scan,
            `ATTENDANCE_${response.status.toUpperCase().replace(/[^A-Z0-9_]/g, "_")}`,
            ownerUserId,
          );
        } else {
          await removePendingForOwner(scan.id, ownerUserId);
        }
      });
    } catch (storageError) {
      await withOwnerQueueLock(
        ownerUserId,
        () => releasePendingAttendanceDelivery(scan.id, ownerUserId),
      ).catch(() => undefined);
      throw storageError;
    }
    announceScheduleChanged();

    if (getCurrentUserId() === ownerUserId && scan.groupId) {
      writeAttendanceSessionProgress(scan.groupId, scan.sessionId, {
        scanned_count: response.scanned_count,
        assigned_count: response.assigned_count,
      });
    }
    updates.push({
      sessionId: scan.sessionId,
      status: response.status,
      message: response.message,
      scannedCount: response.scanned_count,
      assignedCount: response.assigned_count,
    });
    if (isSuccessfulAttendanceReplayStatus(response.status)) {
      synced += 1;
    } else {
      discarded += 1;
    }
  }

  const remaining = await withOwnerQueueLock(
    ownerUserId,
    () => listPendingForOwner(ownerUserId),
  );
  const nextAttemptAt = earliestAttendanceAttemptAt(
    remaining.filter((row) => row.deliveryState !== "sending"),
  );
  announceScheduleChanged();
  return { synced, failed, discarded, updates, nextAttemptAt };
}

async function quarantineRejectedAttendanceScan(
  scan: PendingAttendanceScan,
  errorCode: string,
  ownerUserId: string,
) {
  if (scan.ownerUserId !== ownerUserId) return;
  const db = await openDb();
  try {
    const transaction = db.transaction(
      [PENDING_STORE_NAME, REJECTED_STORE_NAME],
      "readwrite",
    );
    const completion = transactionToPromise(transaction);
    const pendingStore = transaction.objectStore(PENDING_STORE_NAME);
    const current = await requestToPromise<PendingAttendanceScan | undefined>(
      pendingStore.get(scan.id),
    );
    if (current?.ownerUserId === ownerUserId) {
      const rejectedScan: RejectedAttendanceScan = createRejectedAttendanceScan(
        current,
        errorCode,
      );
      transaction.objectStore(REJECTED_STORE_NAME).put(rejectedScan);
      pendingStore.delete(scan.id);
    }
    await completion;
  } finally {
    db.close();
  }
}

async function markPendingAttendanceRetry(
  scan: PendingAttendanceScan,
  error: unknown,
  ownerUserId: string,
) {
  const retry = attendanceRetryState({
    previousAttemptCount: scan.attemptCount,
    retryAfterMs: getRetryAfterMs(error),
  });
  const db = await openDb();
  try {
    const transaction = db.transaction(PENDING_STORE_NAME, "readwrite");
    const completion = transactionToPromise(transaction);
    const store = transaction.objectStore(PENDING_STORE_NAME);
    const current = await requestToPromise<PendingAttendanceScan | undefined>(
      store.get(scan.id),
    );
    if (current?.ownerUserId === ownerUserId) {
      store.put({
        ...current,
        ...retry,
        deliveryState: "pending",
        deliveryStartedAt: undefined,
        lastAttemptAt: new Date().toISOString(),
      });
    }
    await completion;
  } finally {
    db.close();
  }
}

async function claimPendingAttendanceDelivery(
  id: string,
  ownerUserId: string,
): Promise<PendingAttendanceScan | null> {
  const db = await openDb();
  try {
    const transaction = db.transaction(PENDING_STORE_NAME, "readwrite");
    const completion = transactionToPromise(transaction);
    const store = transaction.objectStore(PENDING_STORE_NAME);
    const current = await requestToPromise<PendingAttendanceScan | undefined>(store.get(id));
    if (
      !current
      || current.ownerUserId !== ownerUserId
      || current.deliveryState === "sending"
      || !isAttendanceAttemptEligible(current.nextAttemptAt, current.queuedAt)
    ) {
      await completion;
      return null;
    }
    const claimed: PendingAttendanceScan = {
      ...current,
      deliveryState: "sending",
      deliveryStartedAt: new Date().toISOString(),
    };
    store.put(claimed);
    await completion;
    return claimed;
  } finally {
    db.close();
  }
}

async function releasePendingAttendanceDelivery(id: string, ownerUserId: string) {
  const db = await openDb();
  try {
    const transaction = db.transaction(PENDING_STORE_NAME, "readwrite");
    const completion = transactionToPromise(transaction);
    const store = transaction.objectStore(PENDING_STORE_NAME);
    const current = await requestToPromise<PendingAttendanceScan | undefined>(store.get(id));
    if (current?.ownerUserId === ownerUserId && current.deliveryState === "sending") {
      store.put({
        ...current,
        deliveryState: "pending",
        deliveryStartedAt: undefined,
      });
    }
    await completion;
  } finally {
    db.close();
  }
}

export async function tryRecordAttendanceScan(scan: AttendanceScanInput): Promise<
  | { mode: "online"; response: AttendanceScanResponse }
  | { mode: "queued"; pending: PendingAttendanceScan; duplicate: boolean }
> {
  if (!navigator.onLine) {
    const queued = await enqueueAttendanceScan(scan);
    return { mode: "queued", pending: queued.pending, duplicate: queued.duplicate };
  }

  try {
    const response = await operationsApi.scanMyAttendanceSession({
      sessionId: scan.sessionId,
      qrPayload: scan.qrPayload,
      clientEventId: scan.clientEventId,
      scannedAt: scan.scannedAt,
      deviceId: scan.deviceId,
      syncSource: "online",
    });
    return { mode: "online", response };
  } catch (error) {
    if (isLikelyNetworkFailure(error)) {
      const queued = await enqueueAttendanceScan(scan, error);
      return { mode: "queued", pending: queued.pending, duplicate: queued.duplicate };
    }
    throw error;
  }
}

export async function getBrowserAttendanceQueueSafetySnapshot(): Promise<BrowserAttendanceQueueSafetySnapshot> {
  const ownerUserId = requireCurrentUserId();
  return readQueueSafetySnapshot(ownerUserId);
}

export async function collectBrowserAttendanceQueueCloseout({
  authentication,
  groupId,
  sessionId,
}: {
  authentication: Readonly<{ sessionVersion: number; userId: string }>;
  groupId: string;
  sessionId: string;
}): Promise<AttendanceCloseoutQueueCounts & { unreviewedRejected: number }> {
  return withOwnerQueueLock(
    authentication.userId,
    () => collectQueueCloseoutUnlocked(authentication, groupId, sessionId),
  );
}

export async function publishBrowserAttendanceQueueCloseout<T>({
  authentication,
  groupId,
  publish,
  sessionId,
}: {
  authentication: Readonly<{ sessionVersion: number; userId: string }>;
  groupId: string;
  publish: (
    queue: AttendanceCloseoutQueueCounts & { unreviewedRejected: number },
  ) => Promise<T>;
  sessionId: string;
}): Promise<T> {
  return withOwnerQueueLock(authentication.userId, async () => {
    const queue = await collectQueueCloseoutUnlocked(
      authentication,
      groupId,
      sessionId,
    );
    assertAuthenticationSnapshotCurrent(authentication);
    const result = await publish(queue);
    assertAuthenticationSnapshotCurrent(authentication);
    return result;
  });
}

async function collectQueueCloseoutUnlocked(
  authentication: Readonly<{ sessionVersion: number; userId: string }>,
  groupId: string,
  sessionId: string,
) {
  assertAuthenticationSnapshotCurrent(authentication);
  const [pendingRows, rejectedRows] = await Promise.all([
    listPendingForOwner(authentication.userId),
    listRejectedForOwner(authentication.userId),
  ]);
  assertAuthenticationSnapshotCurrent(authentication);
  if (
    pendingRows.some((row) => row.ownerUserId !== authentication.userId)
    || rejectedRows.some((row) => row.ownerUserId !== authentication.userId)
  ) {
    throw new Error("Closeout evidence crossed an attendance queue owner boundary.");
  }
  const counts = classifyAttendanceCloseoutQueue(pendingRows, groupId, sessionId);
  const unreviewedRejected = rejectedRows.filter(
    (row) => (!row.groupId || row.groupId === groupId)
      && row.sessionId === sessionId,
  ).length;
  assertAuthenticationSnapshotCurrent(authentication);
  return { ...counts, unreviewedRejected };
}

export async function runAttendanceQueueLogoutBoundary<T>(
  ownerUserId: string,
  disposition: AttendanceQueueLogoutDisposition,
  onAllowed: () => Promise<T>,
): Promise<
  | { allowed: false; snapshot: BrowserAttendanceQueueSafetySnapshot }
  | { allowed: true; snapshot: BrowserAttendanceQueueSafetySnapshot; value: T }
> {
  return withOwnerQueueLock(ownerUserId, async () => {
    assertCurrentOwner(ownerUserId);
    const snapshot = await readQueueSafetySnapshot(ownerUserId);
    if (disposition === "block" && hasUnsafeBrowserAttendanceQueue(snapshot)) {
      return { allowed: false, snapshot };
    }
    if (disposition === "discard") {
      await purgeQueueForOwner(ownerUserId);
      announceScheduleChanged();
    }
    assertCurrentOwner(ownerUserId);
    const value = await onAllowed();
    return { allowed: true, snapshot, value };
  });
}

export function subscribeAttendanceQueueScheduleChanges(listener: () => void) {
  if (typeof window === "undefined") return () => undefined;
  const handle = () => listener();
  window.addEventListener(SCHEDULE_EVENT, handle);
  let channel: BroadcastChannel | null = null;
  if ("BroadcastChannel" in window) {
    channel = new BroadcastChannel(SCHEDULE_CHANNEL);
    channel.onmessage = handle;
  }
  return () => {
    window.removeEventListener(SCHEDULE_EVENT, handle);
    channel?.close();
  };
}

async function readQueueSafetySnapshot(
  ownerUserId: string,
): Promise<BrowserAttendanceQueueSafetySnapshot> {
  const [pendingRows, reviewRows] = await Promise.all([
    listPendingForOwner(ownerUserId),
    listRejectedForOwner(ownerUserId),
  ]);
  const sending = pendingRows.filter((row) => row.deliveryState === "sending").length;
  const retryable = pendingRows.filter(
    (row) => row.deliveryState !== "sending" && row.attemptCount > 0,
  ).length;
  const pending = pendingRows.length - retryable - sending;
  const oldestQueuedAt = pendingRows
    .map((row) => row.queuedAt)
    .sort((left, right) => left.localeCompare(right))[0] ?? null;
  return {
    ownerUserId,
    pending,
    sending,
    retryable,
    review: reviewRows.length,
    oldestQueuedAt,
    nextAttemptAt: earliestAttendanceAttemptAt(
      pendingRows.filter((row) => row.deliveryState !== "sending"),
    ),
  };
}

async function purgeQueueForOwner(ownerUserId: string) {
  const db = await openDb();
  try {
    const transaction = db.transaction(
      [PENDING_STORE_NAME, REJECTED_STORE_NAME],
      "readwrite",
    );
    const completion = transactionToPromise(transaction);
    for (const storeName of [PENDING_STORE_NAME, REJECTED_STORE_NAME]) {
      const store = transaction.objectStore(storeName);
      const rows = await requestToPromise<Array<{ id: string }>>(
        store.index(OWNER_INDEX).getAll(ownerUserId),
      );
      for (const row of rows) store.delete(row.id);
    }
    await completion;
  } finally {
    db.close();
  }
}

async function listPendingForOwner(ownerUserId: string) {
  const db = await openDb();
  try {
    const store = db.transaction(PENDING_STORE_NAME, "readonly")
      .objectStore(PENDING_STORE_NAME);
    const scans = await requestToPromise<PendingAttendanceScan[]>(
      store.index(OWNER_INDEX).getAll(ownerUserId),
    );
    return scans.sort((left, right) => left.queuedAt.localeCompare(right.queuedAt));
  } finally {
    db.close();
  }
}

async function listRejectedForOwner(ownerUserId: string) {
  const db = await openDb();
  try {
    const store = db.transaction(REJECTED_STORE_NAME, "readonly")
      .objectStore(REJECTED_STORE_NAME);
    return requestToPromise<RejectedAttendanceScan[]>(
      store.index(OWNER_INDEX).getAll(ownerUserId),
    );
  } finally {
    db.close();
  }
}

async function removePendingForOwner(id: string, ownerUserId: string) {
  const db = await openDb();
  try {
    const transaction = db.transaction(PENDING_STORE_NAME, "readwrite");
    const completion = transactionToPromise(transaction);
    const store = transaction.objectStore(PENDING_STORE_NAME);
    const existing = await requestToPromise<PendingAttendanceScan | undefined>(
      store.get(id),
    );
    if (existing?.ownerUserId === ownerUserId) store.delete(id);
    await completion;
  } finally {
    db.close();
  }
}

function openDb() {
  return new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = (event) => {
      const db = request.result;
      const upgrade = request.transaction;
      if (!upgrade) return;
      if (db.objectStoreNames.contains(PENDING_STORE_NAME) && event.oldVersion < 2) {
        db.deleteObjectStore(PENDING_STORE_NAME);
      }
      ensureOwnerStore(db, upgrade, PENDING_STORE_NAME);
      ensureOwnerStore(db, upgrade, REJECTED_STORE_NAME);
    };
    request.onsuccess = () => {
      const db = request.result;
      db.onversionchange = () => db.close();
      const migration = privacyMigrationPromise ??= withBrowserLock(
        MIGRATION_LOCK,
        () => migrateLegacyQueueRecords(db),
      ).catch((error: unknown) => {
        privacyMigrationPromise = null;
        throw error;
      });
      migration.then(() => resolve(db)).catch((error: unknown) => {
        db.close();
        reject(error);
      });
    };
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error("Offline scan database upgrade is blocked."));
  });
}

function ensureOwnerStore(
  db: IDBDatabase,
  upgrade: IDBTransaction,
  storeName: string,
) {
  const store = db.objectStoreNames.contains(storeName)
    ? upgrade.objectStore(storeName)
    : db.createObjectStore(storeName, { keyPath: "id" });
  if (!store.indexNames.contains(OWNER_INDEX)) {
    store.createIndex(OWNER_INDEX, "ownerUserId", { unique: false });
  }
}

async function migrateLegacyQueueRecords(db: IDBDatabase) {
  const pendingRows = await readAllUnknown(db, PENDING_STORE_NAME);
  const rejectedRows = await readAllUnknown(db, REJECTED_STORE_NAME);
  const normalizedPending = await Promise.all(
    pendingRows.map(normalizePendingAttendanceScan),
  );
  const normalizedRejected = await Promise.all(
    rejectedRows.map(sanitizeLegacyRejectedAttendanceScan),
  );
  const transaction = db.transaction(
    [PENDING_STORE_NAME, REJECTED_STORE_NAME],
    "readwrite",
  );
  const completion = transactionToPromise(transaction);
  replaceMigratedRows(
    transaction.objectStore(PENDING_STORE_NAME),
    pendingRows,
    normalizedPending,
  );
  replaceMigratedRows(
    transaction.objectStore(REJECTED_STORE_NAME),
    rejectedRows,
    normalizedRejected,
  );
  await completion;
}

async function normalizePendingAttendanceScan(
  candidate: Record<string, unknown>,
): Promise<PendingAttendanceScan | null> {
  const ownerUserId = stringValue(candidate.ownerUserId);
  const sessionId = stringValue(candidate.sessionId);
  const qrPayload = stringValue(candidate.qrPayload);
  const clientEventId = stringValue(candidate.clientEventId);
  const scannedAt = stringValue(candidate.scannedAt);
  const deviceId = stringValue(candidate.deviceId);
  const queuedAt = stringValue(candidate.queuedAt);
  if (!ownerUserId || !sessionId || !qrPayload || !clientEventId || !scannedAt || !deviceId || !queuedAt) {
    return null;
  }
  const groupId = stringValue(candidate.groupId) ?? undefined;
  const existingReference = stringValue(candidate.scanReference) ?? undefined;
  const scanReference = isAttendanceScanReference(existingReference)
    ? existingReference
    : await createAttendanceScanReference({ ownerUserId, groupId, sessionId, qrPayload });
  const attemptCount = typeof candidate.attemptCount === "number"
    ? Math.max(0, Math.trunc(candidate.attemptCount))
    : 0;
  const nextAttemptAt = normalizedIso(candidate.nextAttemptAt, queuedAt);
  const lastAttemptAt = normalizedOptionalIso(candidate.lastAttemptAt);
  const legacyDeliveryStartedAt = normalizedOptionalIso(candidate.deliveryStartedAt);
  const deliveryIsFresh = candidate.deliveryState === "sending"
    && legacyDeliveryStartedAt !== undefined
    && Date.now() - Date.parse(legacyDeliveryStartedAt) <= 2 * 60_000;
  return {
    id: attendanceQueueRowId(scanReference),
    scanReference,
    ownerUserId,
    ...(groupId ? { groupId } : {}),
    sessionId,
    qrPayload,
    clientEventId,
    scannedAt,
    deviceId,
    queuedAt,
    attemptCount,
    nextAttemptAt,
    // Preserve a recent cross-tab delivery lease; recover a stale/crashed one.
    deliveryState: deliveryIsFresh ? "sending" : "pending",
    ...(deliveryIsFresh ? { deliveryStartedAt: legacyDeliveryStartedAt } : {}),
    ...(lastAttemptAt ? { lastAttemptAt } : {}),
  };
}

function replaceMigratedRows<T extends { id: string }>(
  store: IDBObjectStore,
  originals: Record<string, unknown>[],
  replacements: Array<T | null>,
) {
  originals.forEach((original, index) => {
    const oldId = stringValue(original.id);
    const replacement = replacements[index];
    if (oldId && (!replacement || oldId !== replacement.id)) store.delete(oldId);
    if (replacement) store.put(replacement);
  });
}

async function readAllUnknown(db: IDBDatabase, storeName: string) {
  const store = db.transaction(storeName, "readonly").objectStore(storeName);
  return requestToPromise<Record<string, unknown>[]>(store.getAll());
}

function normalizedIso(value: unknown, fallback: string) {
  const candidate = stringValue(value);
  return candidate && Number.isFinite(Date.parse(candidate)) ? candidate : fallback;
}

function normalizedOptionalIso(value: unknown) {
  const candidate = stringValue(value);
  return candidate && Number.isFinite(Date.parse(candidate)) ? candidate : undefined;
}

function stringValue(value: unknown) {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function requestToPromise<T>(request: IDBRequest<T>) {
  return new Promise<T>((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function transactionToPromise(transaction: IDBTransaction) {
  return new Promise<void>((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(
      transaction.error ?? new Error("Offline scan transaction failed."),
    );
    transaction.onabort = () => reject(
      transaction.error ?? new Error("Offline scan transaction was aborted."),
    );
  });
}

function isLikelyNetworkFailure(error: unknown) {
  if (!navigator.onLine) return true;
  const code = getErrorCode(error);
  const message = getErrorMessage(error);
  return isRecoverableAttendanceScanError(code)
    || code === "NETWORK_ERROR"
    || code === "REQUEST_TIMEOUT"
    || /network|fetch|timeout|offline|connection/i.test(message);
}

function getErrorCode(error: unknown) {
  if (typeof error !== "object" || error === null || !("code" in error)) return "";
  return String(error.code);
}

function getRetryAfterMs(error: unknown) {
  if (typeof error !== "object" || error === null || !("retryAfterMs" in error)) {
    return undefined;
  }
  const value = Number(error.retryAfterMs);
  return Number.isFinite(value) ? Math.max(0, value) : undefined;
}

function getErrorMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  if (typeof error !== "object" || error === null || !("message" in error)) return "";
  return String(error.message);
}

function getCurrentUserId() {
  return useAuthStore.getState().user?.id ?? null;
}

function requireCurrentUserId() {
  const userId = getCurrentUserId();
  if (!userId) throw new Error("An authenticated coordinator session is required.");
  return userId;
}

function assertCurrentOwner(ownerUserId: string) {
  if (getCurrentUserId() !== ownerUserId) {
    throw new Error("The authenticated attendance queue owner changed.");
  }
}

function assertAuthenticationSnapshotCurrent(
  authentication: Readonly<{ sessionVersion: number; userId: string }>,
) {
  const current = useAuthStore.getState();
  if (
    current.user?.id !== authentication.userId
    || current.sessionVersion !== authentication.sessionVersion
  ) {
    throw new Error("The coordinator account changed while queue evidence was collected.");
  }
}

function emptySyncResult(): AttendanceScanSyncResult {
  return {
    synced: 0,
    failed: 0,
    discarded: 0,
    updates: [],
    nextAttemptAt: null,
  };
}

function announceScheduleChanged() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(SCHEDULE_EVENT));
  if ("BroadcastChannel" in window) {
    const channel = new BroadcastChannel(SCHEDULE_CHANNEL);
    channel.postMessage({ changed: true });
    channel.close();
  }
}

async function withOwnerQueueLock<T>(
  ownerUserId: string,
  task: () => Promise<T>,
): Promise<T> {
  return withBrowserLock(`${OWNER_LOCK_PREFIX}:${ownerUserId}`, task);
}

async function withBrowserLock<T>(name: string, task: () => Promise<T>): Promise<T> {
  if (typeof navigator !== "undefined" && navigator.locks?.request) {
    return navigator.locks.request(name, { mode: "exclusive" }, task);
  }

  const previous = fallbackOwnerLanes.get(name) ?? Promise.resolve();
  let release: () => void = () => undefined;
  const tail = new Promise<void>((resolve) => {
    release = resolve;
  });
  const queued = previous.catch(() => undefined).then(() => tail);
  fallbackOwnerLanes.set(name, queued);
  await previous.catch(() => undefined);
  try {
    return await task();
  } finally {
    release();
    if (fallbackOwnerLanes.get(name) === queued) fallbackOwnerLanes.delete(name);
  }
}

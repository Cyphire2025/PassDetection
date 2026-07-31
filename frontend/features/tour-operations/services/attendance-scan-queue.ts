import { operationsApi, type AttendanceScanResponse } from "@/features/operations/api/operations.api";
import { useAuthStore } from "@/stores/auth.store";
import { writeAttendanceSessionProgress } from "./attendance-session-progress";
import {
  isPermanentAttendanceScanError,
  isRecoverableAttendanceScanError,
  isSuccessfulAttendanceReplayStatus,
  type AttendanceSyncUpdate,
} from "./attendance-sync-policy";
import {
  projectRejectedAttendanceScanForStorage,
  type RejectedAttendanceScanStorageRecord,
} from "./rejected-attendance-scan-projection";

export interface AttendanceScanInput {
  groupId: string;
  sessionId: string;
  qrPayload: string;
  clientEventId: string;
  scannedAt: string;
  deviceId: string;
}

export interface PendingAttendanceScan extends Omit<AttendanceScanInput, "groupId"> {
  // Optional only for records written by the pre-group-scope queue.
  groupId?: string;
  id: string;
  ownerUserId: string;
  queuedAt: string;
}

export type RejectedAttendanceScan = RejectedAttendanceScanStorageRecord;

export interface AttendanceScanSyncResult {
  synced: number;
  failed: number;
  discarded: number;
  updates: AttendanceScanSyncUpdate[];
}

export type AttendanceScanSyncUpdate = AttendanceSyncUpdate;

const DB_NAME = "passdetection-tour-ops";
const DB_VERSION = 4;
const PENDING_STORE_NAME = "pending-attendance-scans";
const REJECTED_STORE_NAME = "rejected-attendance-scans";
const OWNER_INDEX = "owner-user-id";
let activeSyncPromise: Promise<AttendanceScanSyncResult> | null = null;

export async function enqueueAttendanceScan(scan: AttendanceScanInput) {
  const ownerUserId = requireCurrentUserId();
  const id = getStableScanQueueId(
    ownerUserId,
    scan.groupId,
    scan.sessionId,
    scan.qrPayload,
  );
  const pendingScan: PendingAttendanceScan = {
    ...scan,
    id,
    ownerUserId,
    queuedAt: new Date().toISOString(),
  };
  const db = await openDb();
  try {
    const transaction = db.transaction(PENDING_STORE_NAME, "readwrite");
    const completion = transactionToPromise(transaction);
    const store = transaction.objectStore(PENDING_STORE_NAME);
    const legacyId = `${ownerUserId}:${scan.sessionId}:${scan.qrPayload}`;
    const existing = (
      await requestToPromise<PendingAttendanceScan | undefined>(store.get(id))
    ) ?? (
      await requestToPromise<PendingAttendanceScan | undefined>(store.get(legacyId))
    );
    if (!existing) {
      await requestToPromise(store.put(pendingScan));
    }
    await completion;
    return { pending: existing ?? pendingScan, duplicate: Boolean(existing) };
  } finally {
    db.close();
  }
}

export async function countPendingAttendanceScans(groupId?: string) {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId) return 0;
  const db = await openDb();
  const store = db.transaction(PENDING_STORE_NAME, "readonly").objectStore(PENDING_STORE_NAME);
  const scans = await requestToPromise<PendingAttendanceScan[]>(
    store.index(OWNER_INDEX).getAll(ownerUserId),
  );
  db.close();
  if (!groupId) return scans.length;
  // Pre-group-scope v2/v3 records are included until replayed so an upgrade
  // never hides or destroys an already-saved offline scan.
  return scans.filter((scan) => !scan.groupId || scan.groupId === groupId).length;
}

export async function listPendingAttendanceScans() {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId) return [];
  const db = await openDb();
  const store = db.transaction(PENDING_STORE_NAME, "readonly").objectStore(PENDING_STORE_NAME);
  const scans = await requestToPromise<PendingAttendanceScan[]>(
    store.index(OWNER_INDEX).getAll(ownerUserId),
  );
  db.close();
  return scans.sort((a, b) => a.queuedAt.localeCompare(b.queuedAt));
}

export async function removePendingAttendanceScan(id: string) {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId) return;
  const db = await openDb();
  try {
    const transaction = db.transaction(PENDING_STORE_NAME, "readwrite");
    const completion = transactionToPromise(transaction);
    const store = transaction.objectStore(PENDING_STORE_NAME);
    const existing = await requestToPromise<PendingAttendanceScan | undefined>(store.get(id));
    if (existing?.ownerUserId === ownerUserId) {
      await requestToPromise(store.delete(id));
    }
    await completion;
  } finally {
    db.close();
  }
}

export async function countRejectedAttendanceScans(
  groupId: string | null,
  sessionId: string | null,
) {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId || !groupId || !sessionId) return 0;
  const db = await openDb();
  const store = db.transaction(REJECTED_STORE_NAME, "readonly").objectStore(REJECTED_STORE_NAME);
  const scans = await requestToPromise<RejectedAttendanceScan[]>(
    store.index(OWNER_INDEX).getAll(ownerUserId),
  );
  db.close();
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
    await Promise.all(matchingScans.map((scan) => requestToPromise(store.delete(scan.id))));
    await completion;
    return matchingScans.length;
  } finally {
    db.close();
  }
}

export function syncPendingAttendanceScans() {
  if (activeSyncPromise) return activeSyncPromise;
  if (!navigator.onLine) {
    return Promise.resolve({ synced: 0, failed: 0, discarded: 0, updates: [] });
  }

  const request = performPendingAttendanceScanSync().finally(() => {
    if (activeSyncPromise === request) activeSyncPromise = null;
  });
  activeSyncPromise = request;
  return request;
}

async function performPendingAttendanceScanSync(): Promise<AttendanceScanSyncResult> {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId) return { synced: 0, failed: 0, discarded: 0, updates: [] };
  const scans = await listPendingAttendanceScans();
  let synced = 0;
  let failed = 0;
  let discarded = 0;
  const updates: AttendanceScanSyncUpdate[] = [];

  for (const scan of scans) {
    if (getCurrentUserId() !== ownerUserId || scan.ownerUserId !== ownerUserId) break;
    try {
      const response = await operationsApi.scanMyAttendanceSession({
        sessionId: scan.sessionId,
        qrPayload: scan.qrPayload,
        clientEventId: scan.clientEventId,
        scannedAt: scan.scannedAt,
        deviceId: scan.deviceId,
        syncSource: "offline",
      });
      if (scan.groupId) {
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
      if (!isSuccessfulAttendanceReplayStatus(response.status)) {
        await quarantineRejectedAttendanceScan(
          scan,
          `ATTENDANCE_${response.status.toUpperCase().replace(/[^A-Z0-9_]/g, "_")}`,
        );
        discarded += 1;
        continue;
      }
      await removePendingAttendanceScan(scan.id);
      synced += 1;
    } catch (error) {
      if (isPermanentAttendanceScanError(getErrorCode(error))) {
        await quarantineRejectedAttendanceScan(scan, getErrorCode(error));
        discarded += 1;
      } else {
        failed += 1;
        // A recoverable connectivity/server failure will usually affect every
        // following row too. Preserve the queue and stop this drain so a
        // reconnect cannot fan out hundreds of doomed requests to the VPS.
        break;
      }
    }
  }

  return { synced, failed, discarded, updates };
}

async function quarantineRejectedAttendanceScan(scan: PendingAttendanceScan, errorCode: string) {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId || scan.ownerUserId !== ownerUserId) return;
  const pendingScanId = scan.id;
  const db = await openDb();
  try {
    const transaction = db.transaction([PENDING_STORE_NAME, REJECTED_STORE_NAME], "readwrite");
    const completion = transactionToPromise(transaction);
    const pendingStore = transaction.objectStore(PENDING_STORE_NAME);
    const rejectedStore = transaction.objectStore(REJECTED_STORE_NAME);
    const rejectedScan = projectRejectedAttendanceScanForStorage(scan, {
      rejectedAt: new Date().toISOString(),
      errorCode,
      fallbackClientEventId: scan.clientEventId || createMigrationClientEventId(),
    });
    if (!rejectedScan) {
      throw new Error("The rejected attendance scan could not be projected safely.");
    }
    await requestToPromise(rejectedStore.put(rejectedScan));
    await requestToPromise(pendingStore.delete(pendingScanId));
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
      const queued = await enqueueAttendanceScan(scan);
      return { mode: "queued", pending: queued.pending, duplicate: queued.duplicate };
    }
    throw error;
  }
}

function getStableScanQueueId(
  ownerUserId: string,
  groupId: string,
  sessionId: string,
  qrPayload: string,
) {
  return `${ownerUserId}:${groupId}:${sessionId}:${qrPayload}`;
}

function openDb() {
  return new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = (event) => {
      const db = request.result;
      const upgrade = request.transaction;
      if (!upgrade) return;
      // Version 1 records were not user-scoped. Versions 2 and 3 are preserved
      // and replayed; they remain server-authorized even though they predate
      // the explicit groupId field added to new queue records.
      if (db.objectStoreNames.contains(PENDING_STORE_NAME) && event.oldVersion < 2) {
        db.deleteObjectStore(PENDING_STORE_NAME);
      }
      ensureOwnerScopedStore(db, upgrade, PENDING_STORE_NAME);
      const rejectedStore = ensureOwnerScopedStore(
        db,
        upgrade,
        REJECTED_STORE_NAME,
      );
      if (event.oldVersion < 4) {
        migrateRejectedAttendanceScans(rejectedStore);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function ensureOwnerScopedStore(
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
  return store;
}

function migrateRejectedAttendanceScans(store: IDBObjectStore) {
  const request = store.openCursor();
  request.onsuccess = () => {
    const cursor = request.result;
    if (!cursor) return;

    const migrated = projectRejectedAttendanceScanForStorage(cursor.value, {
      fallbackClientEventId: createMigrationClientEventId(),
    });
    if (!migrated) {
      cursor.delete();
      cursor.continue();
      return;
    }

    store.put(migrated);
    if (cursor.primaryKey !== migrated.id) {
      store.delete(cursor.primaryKey);
    }
    cursor.continue();
  };
}

function createMigrationClientEventId() {
  const randomPart = typeof globalThis.crypto?.randomUUID === "function"
    ? globalThis.crypto.randomUUID()
    : Math.random().toString(36).slice(2);
  return `migrated-${Date.now()}-${randomPart}`;
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

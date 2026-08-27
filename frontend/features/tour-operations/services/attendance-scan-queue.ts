import { operationsApi, type AttendanceScanResponse } from "@/features/operations/api/operations.api";
import { useAuthStore } from "@/stores/auth.store";
import apiClient from "@/lib/api/client";
import { writeAttendanceSessionProgress } from "./attendance-session-progress";
import {
  authorizeBrowserOfflineScan,
  getBrowserAttendanceRuntimeHint,
  type AuthorizedBrowserOfflineScan,
} from "./browser-offline-authorization";
import {
  protectBrowserJson,
  unprotectBrowserJson,
  type ProtectedBrowserValue,
} from "./browser-offline-crypto";
import {
  DISCARD_TOMBSTONE_STORE,
  OWNER_USER_ID_INDEX,
  PENDING_ATTENDANCE_STORE,
  REJECTED_ATTENDANCE_STORE,
  openBrowserOfflineDatabase,
} from "./browser-offline-database";
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
import {
  attendanceBatchItemDisposition,
  isMatchingAttendanceBatchEnvelope,
} from "./attendance-batch-policy";

export interface AttendanceScanInput {
  groupId: string;
  sessionId: string;
  qrPayload: string;
  clientEventId: string;
  scannedAt: string;
  deviceId: string;
  /** Registered browser runtime; omitted only for compatibility with legacy rows. */
  runtimeId?: string;
}

export type AttendanceScanRecoveryContext = Readonly<{
  passengerId: string;
  passengerLabel: string;
  sessionLabel: string;
}>;

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
  recovery?: AttendanceScanRecoveryContext;
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
  attemptCount?: number;
  lastAttemptAt?: string;
  recovery?: AttendanceScanRecoveryContext;
}

interface StoredPendingAttendanceScan extends Omit<PendingAttendanceScan, "qrPayload" | "recovery"> {
  protectedQrPayload?: ProtectedBrowserValue;
  // Present only while a legacy row is awaiting copy/verify migration.
  qrPayload?: string;
  recovery?: AttendanceScanRecoveryContext;
  storageVersion?: 5;
}

interface StoredRejectedAttendanceScan extends Omit<RejectedAttendanceScan, "recovery"> {
  protectedRecovery?: ProtectedBrowserValue;
  // Present only until a verified encrypted replacement is written.
  recovery?: AttendanceScanRecoveryContext;
  storageVersion?: 5;
}

export class AttendanceQueueCapacityError extends Error {
  readonly code = "ATTENDANCE_QUEUE_CAPACITY_REACHED";

  constructor() {
    super("Offline attendance storage reached its safe device limit. Reconnect and synchronize before scanning more passengers.");
    this.name = "AttendanceQueueCapacityError";
  }
}

export type AttendanceDiscardReason =
  | "coordinator_confirmed_rescan"
  | "duplicate_local_evidence"
  | "passenger_not_attending"
  | "privacy_or_data_error"
  | "server_terminal_rejection";

export interface AttendanceDiscardTombstone {
  id: string;
  discardEventId: string;
  ownerUserId: string;
  groupId: string;
  sessionId: string;
  installationRuntimeId: string;
  discardedAt: string;
  capturedAt: string;
  reasonCategory: AttendanceDiscardReason;
  scanReference: string;
  syncState: "pending" | "sending" | "rejected" | "synchronized";
  attemptCount: number;
  nextAttemptAt: string;
  lastAttemptAt?: string;
  synchronizedAt?: string;
  serverErrorCode?: string;
}

export interface AttendanceScanSyncResult {
  synced: number;
  failed: number;
  discarded: number;
  updates: AttendanceSyncUpdate[];
  nextAttemptAt: string | null;
}

export type AttendanceScanSyncUpdate = AttendanceSyncUpdate;

const PENDING_STORE_NAME = PENDING_ATTENDANCE_STORE;
const REJECTED_STORE_NAME = REJECTED_ATTENDANCE_STORE;
const OWNER_INDEX = OWNER_USER_ID_INDEX;
const SCHEDULE_EVENT = "passdetection:attendance-queue-schedule-changed";
const SCHEDULE_CHANNEL = "passdetection-attendance-queue-schedule";
const MIGRATION_LOCK = "passdetection-attendance-queue-v4-migration";
const OWNER_LOCK_PREFIX = "passdetection-attendance-owner";
const DRAIN_LOCK_PREFIX = "passdetection-attendance-drain";
const SYNCHRONIZED_DISCARD_RETENTION_MS = 30 * 24 * 60 * 60 * 1_000;
export const MAX_PENDING_ATTENDANCE_SCANS_PER_OWNER = 5_000;

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
  const authorization = await authorizeBrowserOfflineScan({
    groupId: scan.groupId,
    qrPayload: scan.qrPayload,
    sessionId: scan.sessionId,
  });
  const authorizedScan: AttendanceScanInput = {
    ...scan,
    deviceId: authorization.runtimeId,
    runtimeId: authorization.runtimeId,
    scannedAt: authorization.scannedAt,
  };
  return withOwnerQueueLock(ownerUserId, async () => {
    assertCurrentOwner(ownerUserId);
    const scanReference = await createAttendanceScanReference({
      ownerUserId,
      groupId: authorizedScan.groupId,
      sessionId: authorizedScan.sessionId,
      qrPayload: authorizedScan.qrPayload,
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
      ...authorizedScan,
      id,
      scanReference,
      ownerUserId,
      queuedAt,
      ...initialRetry,
      deliveryState: "pending",
      recovery: recoveryContext(authorization),
    };
    const storedPendingScan = await protectPendingAttendanceScan(pendingScan);
    const db = await openDb();
    try {
      assertCurrentOwner(ownerUserId);
      const transaction = db.transaction(PENDING_STORE_NAME, "readwrite");
      const completion = transactionToPromise(transaction);
      const store = transaction.objectStore(PENDING_STORE_NAME);
      const existing = await requestToPromise<StoredPendingAttendanceScan | undefined>(
        store.get(id),
      );
      if (!existing) {
        const ownerRowCount = await requestToPromise(
          store.index(OWNER_INDEX).count(ownerUserId),
        );
        if (ownerRowCount >= MAX_PENDING_ATTENDANCE_SCANS_PER_OWNER) {
          throw new AttendanceQueueCapacityError();
        }
        await requestToPromise(store.put(storedPendingScan));
      }
      await completion;
      announceScheduleChanged();
      return {
        pending: existing ? await restorePendingAttendanceScan(existing) : pendingScan,
        duplicate: Boolean(existing),
      };
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
  const [rows, discardRows] = await Promise.all([
    listPendingForOwner(ownerUserId),
    listDiscardTombstonesForOwner(ownerUserId),
  ]);
  const scanAttemptAt = earliestAttendanceAttemptAt(
    rows.filter((row) => row.deliveryState !== "sending"),
  );
  const discardAttemptAt = earliestAttendanceAttemptAt(
    discardRows
      .filter((row) => row.syncState === "pending")
      .map((row) => ({ nextAttemptAt: row.nextAttemptAt, queuedAt: row.discardedAt })),
  );
  if (!scanAttemptAt) return discardAttemptAt;
  if (!discardAttemptAt) return scanAttemptAt;
  return scanAttemptAt.localeCompare(discardAttemptAt) <= 0
    ? scanAttemptAt
    : discardAttemptAt;
}

export async function removePendingAttendanceScan(
  id: string,
  reasonCategory: AttendanceDiscardReason = "coordinator_confirmed_rescan",
) {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId) return;
  await withOwnerQueueLock(ownerUserId, async () => {
    const db = await openDb();
    try {
      const transaction = db.transaction(
        [PENDING_STORE_NAME, DISCARD_TOMBSTONE_STORE],
        "readwrite",
      );
      const completion = transactionToPromise(transaction);
      const pendingStore = transaction.objectStore(PENDING_STORE_NAME);
      const row = await requestToPromise<StoredPendingAttendanceScan | undefined>(
        pendingStore.get(id),
      );
      if (row?.ownerUserId === ownerUserId) {
        transaction.objectStore(DISCARD_TOMBSTONE_STORE)
          .add(createDiscardTombstone(row, reasonCategory));
        pendingStore.delete(id);
      }
      await completion;
    } finally {
      db.close();
    }
    announceScheduleChanged();
    if (navigator.onLine) void syncAttendanceDiscardTombstones().catch(() => undefined);
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

export async function listRejectedAttendanceScans(
  groupId: string | null,
  sessionId: string | null,
) {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId || !groupId || !sessionId) return [];
  const rows = await listRejectedForOwner(ownerUserId);
  return rows
    .filter((scan) => (!scan.groupId || scan.groupId === groupId) && scan.sessionId === sessionId)
    .sort((left, right) => right.rejectedAt.localeCompare(left.rejectedAt));
}

export async function acknowledgeRejectedAttendanceScans(
  groupId: string | null,
  sessionId: string | null,
  reasonCategory: AttendanceDiscardReason = "server_terminal_rejection",
) {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId || !groupId || !sessionId) return 0;
  return withOwnerQueueLock(ownerUserId, async () => {
    assertCurrentOwner(ownerUserId);
    const db = await openDb();
    try {
      const transaction = db.transaction(
        [REJECTED_STORE_NAME, DISCARD_TOMBSTONE_STORE],
        "readwrite",
      );
      const completion = transactionToPromise(transaction);
      const store = transaction.objectStore(REJECTED_STORE_NAME);
      const scans = await requestToPromise<StoredRejectedAttendanceScan[]>(
        store.index(OWNER_INDEX).getAll(ownerUserId),
      );
      const matchingScans = scans.filter(
        (scan) => scan.groupId === groupId
          && scan.sessionId === sessionId,
      );
      const tombstoneStore = transaction.objectStore(DISCARD_TOMBSTONE_STORE);
      for (const scan of matchingScans) {
        tombstoneStore.add(createDiscardTombstone(scan, reasonCategory));
        store.delete(scan.id);
      }
      await completion;
      announceScheduleChanged();
      if (navigator.onLine) void syncAttendanceDiscardTombstones().catch(() => undefined);
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

export async function countPendingAttendanceDiscardAudits(
  groupId?: string,
  sessionId?: string,
) {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId) return 0;
  const rows = await listDiscardTombstonesForOwner(ownerUserId);
  return rows.filter((row) => (
    row.syncState !== "synchronized"
    && (!groupId || row.groupId === groupId)
    && (!sessionId || row.sessionId === sessionId)
  )).length;
}

interface AttendanceDiscardBatchResponse {
  items: Array<Readonly<{
    discard_event_id: string;
    reason_code: string | null;
    status: "accepted" | "already_applied" | "rejected";
  }>>;
}

/**
 * Synchronizes privacy-safe discard evidence independently from raw scans. The
 * server contract is additive; older backends leave rows retryable instead of
 * causing local deletion.
 */
export async function syncAttendanceDiscardTombstones(): Promise<Readonly<{
  synchronized: number;
  rejected: number;
  pending: number;
}>> {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId || !navigator.onLine) {
    return { synchronized: 0, rejected: 0, pending: ownerUserId
      ? await countPendingAttendanceDiscardAudits()
      : 0 };
  }
  return withOwnerQueueLock(ownerUserId, async () => {
    assertCurrentOwner(ownerUserId);
    await purgeExpiredSynchronizedDiscardTombstones(ownerUserId);
    const allRows = await listDiscardTombstonesForOwner(ownerUserId);
    const candidates = allRows
      .filter((row) => (
        row.syncState === "pending"
        && isAttendanceAttemptEligible(row.nextAttemptAt, row.discardedAt)
      ))
      .slice(0, 50);
    if (candidates.length === 0) {
      return {
        synchronized: 0,
        rejected: 0,
        pending: allRows.filter((row) => row.syncState !== "synchronized").length,
      };
    }
    await updateDiscardTombstones(ownerUserId, candidates.map((row) => ({
      ...row,
      syncState: "sending" as const,
      lastAttemptAt: new Date().toISOString(),
    })));
    let response: AttendanceDiscardBatchResponse;
    try {
      const result = await apiClient.post<AttendanceDiscardBatchResponse>(
        "/api/v1/tour-operations/coordinator/attendance/discards",
        {
          items: candidates.map((row) => ({
            captured_at: row.capturedAt,
            discard_event_id: row.discardEventId,
            discarded_at: row.discardedAt,
            group_id: row.groupId,
            // The backend must derive the authoritative runtime from the
            // httpOnly registration cookie. This is a privacy-safe continuity
            // hint for rolling compatibility, not an authorization claim.
            installation_runtime_id: row.installationRuntimeId,
            reason_category: row.reasonCategory,
            scan_reference: row.scanReference,
            session_id: row.sessionId,
          })),
        },
      );
      response = result.data;
    } catch (error) {
      const retryRows = candidates.map((row) => {
        const retry = attendanceRetryState({
          previousAttemptCount: row.attemptCount,
          retryAfterMs: getRetryAfterMs(error),
        });
        return {
          ...row,
          ...retry,
          lastAttemptAt: new Date().toISOString(),
          syncState: "pending" as const,
        };
      });
      await updateDiscardTombstones(ownerUserId, retryRows);
      announceScheduleChanged();
      throw error;
    }
    assertCurrentOwner(ownerUserId);
    const byEventId = new Map(response.items.map((item) => [item.discard_event_id, item]));
    let synchronized = 0;
    let rejected = 0;
    const updated = candidates.map((row) => {
      const item = byEventId.get(row.discardEventId);
      if (item?.status === "accepted" || item?.status === "already_applied") {
        synchronized += 1;
        return {
          ...row,
          syncState: "synchronized" as const,
          synchronizedAt: new Date().toISOString(),
          lastAttemptAt: new Date().toISOString(),
          serverErrorCode: undefined,
        };
      }
      rejected += 1;
      return {
        ...row,
        syncState: "rejected" as const,
        lastAttemptAt: new Date().toISOString(),
        serverErrorCode: item?.reason_code ?? "DISCARD_RECEIPT_INVALID_RESPONSE",
      };
    });
    await updateDiscardTombstones(ownerUserId, updated);
    announceScheduleChanged();
    return {
      synchronized,
      rejected,
      pending: allRows.filter((row) => row.syncState !== "synchronized").length
        - synchronized,
    };
  });
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
  const handledIds = new Set<string>();

  for (const candidate of scans) {
    if (handledIds.has(candidate.id)) continue;
    if (getCurrentUserId() !== ownerUserId || candidate.ownerUserId !== ownerUserId) break;
    if (!isAttendanceAttemptEligible(candidate.nextAttemptAt, candidate.queuedAt)) continue;
    let chunkResult: AttendanceSyncChunkResult;
    if (isBatchCompatiblePendingScan(candidate)) {
      const batchCandidates = scans
        .filter((scan) => (
          !handledIds.has(scan.id)
          && scan.ownerUserId === ownerUserId
          && scan.sessionId === candidate.sessionId
          && isAttendanceAttemptEligible(scan.nextAttemptAt, scan.queuedAt)
          && isBatchCompatiblePendingScan(scan)
        ))
        .slice(0, 50);
      batchCandidates.forEach((scan) => handledIds.add(scan.id));
      chunkResult = await syncPendingAttendanceScanBatch(batchCandidates, ownerUserId);
    } else {
      handledIds.add(candidate.id);
      // Rows created against an older contract remain deliverable through the
      // original single-scan endpoint. New compatible rows always use the
      // bounded batch contract.
      chunkResult = await syncLegacyPendingAttendanceScan(candidate, ownerUserId);
    }
    synced += chunkResult.synced;
    failed += chunkResult.failed;
    discarded += chunkResult.discarded;
    updates.push(...chunkResult.updates);
    if (chunkResult.stop) break;
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

type AttendanceSyncChunkResult = Omit<AttendanceScanSyncResult, "nextAttemptAt"> & {
  stop: boolean;
};

async function syncPendingAttendanceScanBatch(
  candidates: PendingAttendanceScan[],
  ownerUserId: string,
): Promise<AttendanceSyncChunkResult> {
  const claimed: PendingAttendanceScan[] = [];
  for (const candidate of candidates) {
    if (getCurrentUserId() !== ownerUserId) break;
    const scan = await withOwnerQueueLock(
      ownerUserId,
      () => claimPendingAttendanceDelivery(candidate.id, ownerUserId),
    );
    if (scan) claimed.push(scan);
  }
  if (claimed.length === 0) return emptySyncChunkResult();
  announceScheduleChanged();

  let response: Awaited<ReturnType<typeof operationsApi.scanMyAttendanceSessionBatch>>;
  const batchId = createAttendanceScanBatchId();
  try {
    response = await operationsApi.scanMyAttendanceSessionBatch({
      sessionId: claimed[0].sessionId,
      batchId,
      scans: claimed.map((scan) => ({
        clientEventId: scan.clientEventId,
        qrPayload: scan.qrPayload,
        scannedAt: scan.scannedAt,
      })),
    });
  } catch (error) {
    try {
      for (const scan of claimed) {
        await withOwnerQueueLock(
          ownerUserId,
          () => markPendingAttendanceRetry(scan, error, ownerUserId),
        );
      }
    } catch (storageError) {
      await releaseAttendanceBatchClaims(claimed, ownerUserId);
      throw storageError;
    }
    announceScheduleChanged();
    return {
      synced: 0,
      failed: claimed.length,
      discarded: 0,
      updates: [],
      stop: true,
    };
  }

  const envelopeValid = isMatchingAttendanceBatchEnvelope({
    response,
    expectedBatchId: batchId,
    expectedClientEventIds: claimed.map((scan) => scan.clientEventId),
  });
  const byEventId = envelopeValid
    ? new Map(response.items.map((item) => [item.client_event_id, item]))
    : new Map();
  let synced = 0;
  let failed = 0;
  let discarded = 0;
  let stop = false;
  const updates: AttendanceScanSyncUpdate[] = [];

  try {
    for (const scan of claimed) {
      const item = byEventId.get(scan.clientEventId);
      const disposition = attendanceBatchItemDisposition(item);

      if (disposition === "success") {
        const scanResponse = item.scan as AttendanceScanResponse;
        await withOwnerQueueLock(
          ownerUserId,
          () => removePendingForOwner(scan.id, ownerUserId),
        );
        publishAttendanceProgress(ownerUserId, scan, scanResponse, updates);
        synced += 1;
      } else if (disposition === "terminal-rejection") {
        await withOwnerQueueLock(
          ownerUserId,
          () => quarantineRejectedAttendanceScan(
            scan,
            item.error_code as string,
            ownerUserId,
          ),
        );
        discarded += 1;
      } else {
        await withOwnerQueueLock(
          ownerUserId,
          () => markPendingAttendanceRetry(
            scan,
            { code: item?.error_code ?? "ATTENDANCE_SCAN_BATCH_INVALID_RESPONSE" },
            ownerUserId,
          ),
        );
        failed += 1;
        stop = true;
      }
    }
  } catch (storageError) {
    await releaseAttendanceBatchClaims(claimed, ownerUserId);
    throw storageError;
  }
  announceScheduleChanged();
  return { synced, failed, discarded, updates, stop };
}

async function syncLegacyPendingAttendanceScan(
  candidate: PendingAttendanceScan,
  ownerUserId: string,
): Promise<AttendanceSyncChunkResult> {
  const scan = await withOwnerQueueLock(
    ownerUserId,
    () => claimPendingAttendanceDelivery(candidate.id, ownerUserId),
  );
  if (!scan) return emptySyncChunkResult();
  announceScheduleChanged();

  let response: AttendanceScanResponse;
  try {
    response = await operationsApi.scanMyAttendanceSession({
      sessionId: scan.sessionId,
      qrPayload: scan.qrPayload,
      clientEventId: scan.clientEventId,
      scannedAt: scan.scannedAt,
      deviceId: scan.deviceId,
      runtimeId: scan.runtimeId,
      syncSource: "offline",
    });
  } catch (error) {
    const permanent = isPermanentAttendanceScanError(getErrorCode(error));
    try {
      await withOwnerQueueLock(ownerUserId, () => permanent
        ? quarantineRejectedAttendanceScan(scan, getErrorCode(error), ownerUserId)
        : markPendingAttendanceRetry(scan, error, ownerUserId));
    } catch (storageError) {
      await withOwnerQueueLock(
        ownerUserId,
        () => releasePendingAttendanceDelivery(scan.id, ownerUserId),
      ).catch(() => undefined);
      throw storageError;
    }
    announceScheduleChanged();
    return {
      synced: 0,
      failed: permanent ? 0 : 1,
      discarded: permanent ? 1 : 0,
      updates: [],
      // A recoverable failure will usually affect every following row too.
      stop: !permanent,
    };
  }

  try {
    await withOwnerQueueLock(ownerUserId, () => isSuccessfulAttendanceReplayStatus(response.status)
      ? removePendingForOwner(scan.id, ownerUserId)
      : quarantineRejectedAttendanceScan(
        scan,
        `ATTENDANCE_${response.status.toUpperCase().replace(/[^A-Z0-9_]/g, "_")}`,
        ownerUserId,
      ));
  } catch (storageError) {
    await withOwnerQueueLock(
      ownerUserId,
      () => releasePendingAttendanceDelivery(scan.id, ownerUserId),
    ).catch(() => undefined);
    throw storageError;
  }
  const updates: AttendanceScanSyncUpdate[] = [];
  publishAttendanceProgress(ownerUserId, scan, response, updates);
  announceScheduleChanged();
  return {
    synced: isSuccessfulAttendanceReplayStatus(response.status) ? 1 : 0,
    failed: 0,
    discarded: isSuccessfulAttendanceReplayStatus(response.status) ? 0 : 1,
    updates,
    stop: false,
  };
}

function publishAttendanceProgress(
  ownerUserId: string,
  scan: PendingAttendanceScan,
  response: AttendanceScanResponse,
  updates: AttendanceScanSyncUpdate[],
) {
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
}

function isBatchCompatiblePendingScan(scan: PendingAttendanceScan): boolean {
  return /^[A-Za-z0-9:_-]{8,128}$/.test(scan.clientEventId)
    && /^pdatt:[A-Za-z0-9_-]{43}$/.test(scan.qrPayload)
    && Number.isFinite(Date.parse(scan.scannedAt))
    && /(?:Z|[+-]\d{2}:\d{2})$/.test(scan.scannedAt);
}

function createAttendanceScanBatchId(): string {
  return crypto.randomUUID();
}

async function releaseAttendanceBatchClaims(
  scans: PendingAttendanceScan[],
  ownerUserId: string,
) {
  for (const scan of scans) {
    await withOwnerQueueLock(
      ownerUserId,
      () => releasePendingAttendanceDelivery(scan.id, ownerUserId),
    ).catch(() => undefined);
  }
}

function emptySyncChunkResult(): AttendanceSyncChunkResult {
  return { synced: 0, failed: 0, discarded: 0, updates: [], stop: false };
}

async function quarantineRejectedAttendanceScan(
  scan: PendingAttendanceScan,
  errorCode: string,
  ownerUserId: string,
) {
  if (scan.ownerUserId !== ownerUserId) return;
  const rejectedScan = await protectRejectedAttendanceScan(
    createRejectedAttendanceScan(scan, errorCode),
  );
  const db = await openDb();
  try {
    const transaction = db.transaction(
      [PENDING_STORE_NAME, REJECTED_STORE_NAME],
      "readwrite",
    );
    const completion = transactionToPromise(transaction);
    const pendingStore = transaction.objectStore(PENDING_STORE_NAME);
    const current = await requestToPromise<StoredPendingAttendanceScan | undefined>(
      pendingStore.get(scan.id),
    );
    if (current?.ownerUserId === ownerUserId) {
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
    const current = await requestToPromise<StoredPendingAttendanceScan | undefined>(
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
    const current = await requestToPromise<StoredPendingAttendanceScan | undefined>(store.get(id));
    if (
      !current
      || current.ownerUserId !== ownerUserId
      || current.deliveryState === "sending"
      || !isAttendanceAttemptEligible(current.nextAttemptAt, current.queuedAt)
    ) {
      await completion;
      return null;
    }
    const claimed: StoredPendingAttendanceScan = {
      ...current,
      deliveryState: "sending",
      deliveryStartedAt: new Date().toISOString(),
    };
    store.put(claimed);
    await completion;
    return restorePendingAttendanceScan(claimed);
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
    const current = await requestToPromise<StoredPendingAttendanceScan | undefined>(store.get(id));
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

  // The HttpOnly runtime cookie is authoritative. Its paired UUID is sent as
  // an additive continuity hint; absence keeps older/legacy clients working.
  const runtimeId = scan.runtimeId
    ?? await getBrowserAttendanceRuntimeHint().catch(() => null)
    ?? undefined;

  try {
    const response = await operationsApi.scanMyAttendanceSession({
      sessionId: scan.sessionId,
      qrPayload: scan.qrPayload,
      clientEventId: scan.clientEventId,
      scannedAt: scan.scannedAt,
      deviceId: scan.deviceId,
      runtimeId,
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
}): Promise<AttendanceCloseoutQueueCounts & {
  discardAuditPending: number;
  unreviewedRejected: number;
}> {
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
    queue: AttendanceCloseoutQueueCounts & {
      discardAuditPending: number;
      unreviewedRejected: number;
    },
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
  const [pendingRows, rejectedRows, discardRows] = await Promise.all([
    listPendingForOwner(authentication.userId),
    listRejectedForOwner(authentication.userId),
    listDiscardTombstonesForOwner(authentication.userId),
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
  const discardAuditPending = discardRows.filter((row) => (
    row.groupId === groupId
    && row.sessionId === sessionId
    && row.syncState !== "synchronized"
  )).length;
  return { ...counts, discardAuditPending, unreviewedRejected };
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
  const [pendingRows, reviewRows, discardRows] = await Promise.all([
    listPendingForOwner(ownerUserId),
    listRejectedForOwner(ownerUserId),
    listDiscardTombstonesForOwner(ownerUserId),
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
    discardAuditPending: discardRows.filter((row) => row.syncState !== "synchronized").length,
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
      [PENDING_STORE_NAME, REJECTED_STORE_NAME, DISCARD_TOMBSTONE_STORE],
      "readwrite",
    );
    const completion = transactionToPromise(transaction);
    const pendingStore = transaction.objectStore(PENDING_STORE_NAME);
    const rejectedStore = transaction.objectStore(REJECTED_STORE_NAME);
    const tombstoneStore = transaction.objectStore(DISCARD_TOMBSTONE_STORE);
    const pendingRows = await requestToPromise<StoredPendingAttendanceScan[]>(
      pendingStore.index(OWNER_INDEX).getAll(ownerUserId),
    );
    const rejectedRows = await requestToPromise<StoredRejectedAttendanceScan[]>(
      rejectedStore.index(OWNER_INDEX).getAll(ownerUserId),
    );
    for (const row of [...pendingRows, ...rejectedRows]) {
      if (!row.groupId) {
        // An old unscoped row cannot be attributed safely. Preserve it and
        // keep logout blocked instead of manufacturing incorrect audit data.
        continue;
      }
      tombstoneStore.add(createDiscardTombstone(row, "privacy_or_data_error"));
      if ("deliveryState" in row) pendingStore.delete(row.id);
      else rejectedStore.delete(row.id);
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
    const storedScans = await requestToPromise<StoredPendingAttendanceScan[]>(
      store.index(OWNER_INDEX).getAll(ownerUserId),
    );
    const scans = await Promise.all(storedScans.map(restorePendingAttendanceScan));
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
    const storedScans = await requestToPromise<StoredRejectedAttendanceScan[]>(
      store.index(OWNER_INDEX).getAll(ownerUserId),
    );
    return Promise.all(storedScans.map(restoreRejectedAttendanceScan));
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
    const existing = await requestToPromise<StoredPendingAttendanceScan | undefined>(
      store.get(id),
    );
    if (existing?.ownerUserId === ownerUserId) store.delete(id);
    await completion;
  } finally {
    db.close();
  }
}

async function openDb() {
  const database = await openBrowserOfflineDatabase();
  const migration = privacyMigrationPromise ??= withBrowserLock(
    MIGRATION_LOCK,
    () => migrateLegacyQueueRecords(database),
  ).catch((error: unknown) => {
    privacyMigrationPromise = null;
    throw error;
  });
  try {
    await migration;
    return database;
  } catch (error) {
    database.close();
    throw error;
  }
}

async function listDiscardTombstonesForOwner(ownerUserId: string) {
  const db = await openDb();
  try {
    const store = db.transaction(DISCARD_TOMBSTONE_STORE, "readonly")
      .objectStore(DISCARD_TOMBSTONE_STORE);
    return requestToPromise<AttendanceDiscardTombstone[]>(
      store.index(OWNER_INDEX).getAll(ownerUserId),
    );
  } finally {
    db.close();
  }
}

async function updateDiscardTombstones(
  ownerUserId: string,
  rows: AttendanceDiscardTombstone[],
) {
  const db = await openDb();
  try {
    const transaction = db.transaction(DISCARD_TOMBSTONE_STORE, "readwrite");
    const completion = transactionToPromise(transaction);
    const store = transaction.objectStore(DISCARD_TOMBSTONE_STORE);
    for (const row of rows) {
      if (row.ownerUserId === ownerUserId) store.put(row);
    }
    await completion;
  } finally {
    db.close();
  }
}

async function purgeExpiredSynchronizedDiscardTombstones(ownerUserId: string) {
  const cutoff = Date.now() - SYNCHRONIZED_DISCARD_RETENTION_MS;
  const db = await openDb();
  try {
    const transaction = db.transaction(DISCARD_TOMBSTONE_STORE, "readwrite");
    const completion = transactionToPromise(transaction);
    const store = transaction.objectStore(DISCARD_TOMBSTONE_STORE);
    const rows = await requestToPromise<AttendanceDiscardTombstone[]>(
      store.index(OWNER_INDEX).getAll(ownerUserId),
    );
    for (const row of rows) {
      const synchronizedAt = row.synchronizedAt
        ? Date.parse(row.synchronizedAt)
        : Number.NaN;
      if (
        row.syncState === "synchronized"
        && Number.isFinite(synchronizedAt)
        && synchronizedAt < cutoff
      ) {
        store.delete(row.id);
      }
    }
    await completion;
  } finally {
    db.close();
  }
}

function createDiscardTombstone(
  scan: Readonly<{
    deviceId: string;
    groupId?: string;
    ownerUserId: string;
    scanReference: string;
    scannedAt: string;
    sessionId: string;
  }>,
  reasonCategory: AttendanceDiscardReason,
): AttendanceDiscardTombstone {
  if (!scan.groupId) throw new Error("A group-scoped scan is required for discard evidence.");
  const discardEventId = crypto.randomUUID();
  const discardedAt = new Date().toISOString();
  return {
    id: `attendance-discard:${discardEventId}`,
    discardEventId,
    ownerUserId: scan.ownerUserId,
    groupId: scan.groupId,
    sessionId: scan.sessionId,
    installationRuntimeId: scan.deviceId,
    discardedAt,
    capturedAt: scan.scannedAt,
    reasonCategory,
    scanReference: scan.scanReference,
    syncState: "pending",
    attemptCount: 0,
    nextAttemptAt: discardedAt,
  };
}

async function migrateLegacyQueueRecords(db: IDBDatabase) {
  const pendingRows = await readAllUnknown(db, PENDING_STORE_NAME);
  const rejectedRows = await readAllUnknown(db, REJECTED_STORE_NAME);
  const normalizedPending = await Promise.all(
    pendingRows.map((row) => normalizePendingAttendanceScan(row).catch(() => null)),
  );
  const normalizedRejected = await Promise.all(
    rejectedRows.map((row) => normalizeRejectedAttendanceScan(row).catch(() => null)),
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

async function protectPendingAttendanceScan(
  scan: PendingAttendanceScan,
): Promise<StoredPendingAttendanceScan> {
  const { qrPayload, recovery, ...metadata } = scan;
  const protectedQrPayload = await protectBrowserJson(
    { qrPayload, ...(recovery ? { recovery } : {}) },
    pendingScanAssociatedData(metadata),
  );
  return {
    ...metadata,
    protectedQrPayload,
    storageVersion: 5,
  };
}

async function restorePendingAttendanceScan(
  stored: StoredPendingAttendanceScan,
): Promise<PendingAttendanceScan> {
  let qrPayload = stored.qrPayload;
  let recovery = normalizeRecoveryContext(stored.recovery);
  if (!qrPayload && stored.storageVersion === 5 && stored.protectedQrPayload) {
    const decrypted = await unprotectBrowserJson<{
      qrPayload?: unknown;
      recovery?: unknown;
    }>(
      stored.protectedQrPayload,
      pendingScanAssociatedData(stored),
    );
    qrPayload = typeof decrypted.qrPayload === "string" ? decrypted.qrPayload : undefined;
    recovery = normalizeRecoveryContext(decrypted.recovery) ?? recovery;
  }
  if (!qrPayload || !/^pdatt:[A-Za-z0-9_-]{43}$/.test(qrPayload)) {
    throw new Error("A protected attendance queue row is corrupt.");
  }
  const expectedReference = await createAttendanceScanReference({
    ownerUserId: stored.ownerUserId,
    groupId: stored.groupId,
    sessionId: stored.sessionId,
    qrPayload,
  });
  if (
    expectedReference !== stored.scanReference
    || attendanceQueueRowId(expectedReference) !== stored.id
  ) {
    throw new Error("A protected attendance queue row failed its identity check.");
  }
  const restored = { ...stored, qrPayload };
  delete restored.protectedQrPayload;
  delete restored.storageVersion;
  delete restored.recovery;
  return { ...restored, ...(recovery ? { recovery } : {}) };
}

async function protectRejectedAttendanceScan(
  scan: RejectedAttendanceScan,
): Promise<StoredRejectedAttendanceScan> {
  const { recovery, ...metadata } = scan;
  const protectedRecovery = recovery
    ? await protectBrowserJson(
        { recovery },
        rejectedScanAssociatedData(metadata),
      )
    : undefined;
  return {
    ...metadata,
    ...(protectedRecovery ? { protectedRecovery } : {}),
    storageVersion: 5,
  };
}

async function restoreRejectedAttendanceScan(
  stored: StoredRejectedAttendanceScan,
): Promise<RejectedAttendanceScan> {
  let recovery = normalizeRecoveryContext(stored.recovery);
  if (stored.storageVersion === 5 && stored.protectedRecovery) {
    const decrypted = await unprotectBrowserJson<{ recovery?: unknown }>(
      stored.protectedRecovery,
      rejectedScanAssociatedData(stored),
    );
    recovery = normalizeRecoveryContext(decrypted.recovery) ?? recovery;
  }
  const restored = { ...stored };
  delete restored.protectedRecovery;
  delete restored.storageVersion;
  delete restored.recovery;
  return { ...restored, ...(recovery ? { recovery } : {}) };
}

function pendingScanAssociatedData(scan: Readonly<{
  groupId?: string;
  id: string;
  ownerUserId: string;
  sessionId: string;
}>) {
  return JSON.stringify([
    "attendance-pending-v5",
    scan.id,
    scan.ownerUserId,
    scan.groupId ?? "legacy-group",
    scan.sessionId,
  ]);
}

function rejectedScanAssociatedData(scan: Readonly<{
  id: string;
  ownerUserId: string;
  scanReference: string;
}>) {
  return JSON.stringify([
    "attendance-rejected-v5",
    scan.id,
    scan.ownerUserId,
    scan.scanReference,
  ]);
}

function isProtectedBrowserValue(value: unknown): value is ProtectedBrowserValue {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<ProtectedBrowserValue>;
  return candidate.version === 1
    && candidate.algorithm === "AES-GCM"
    && candidate.keyId === "coordinator-offline-aes-gcm-v1"
    && candidate.ciphertext instanceof ArrayBuffer
    && candidate.iv instanceof Uint8Array;
}

function recoveryContext(
  authorization: AuthorizedBrowserOfflineScan,
): AttendanceScanRecoveryContext {
  return {
    passengerId: authorization.passengerId,
    passengerLabel: authorization.passengerLabel,
    sessionLabel: authorization.sessionLabel,
  };
}

function normalizeRecoveryContext(value: unknown): AttendanceScanRecoveryContext | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const candidate = value as Partial<AttendanceScanRecoveryContext>;
  if (
    typeof candidate.passengerId !== "string"
    || candidate.passengerId.length === 0
    || candidate.passengerId.length > 128
    || typeof candidate.passengerLabel !== "string"
    || candidate.passengerLabel.length === 0
    || candidate.passengerLabel.length > 255
    || typeof candidate.sessionLabel !== "string"
    || candidate.sessionLabel.length === 0
    || candidate.sessionLabel.length > 160
  ) {
    return undefined;
  }
  return {
    passengerId: candidate.passengerId,
    passengerLabel: candidate.passengerLabel,
    sessionLabel: candidate.sessionLabel,
  };
}

async function normalizePendingAttendanceScan(
  candidate: Record<string, unknown>,
): Promise<StoredPendingAttendanceScan | null> {
  if (candidate.storageVersion === 5 && isProtectedBrowserValue(candidate.protectedQrPayload)) {
    const existing = candidate as unknown as StoredPendingAttendanceScan;
    const restored = await restorePendingAttendanceScan(existing);
    return normalizeRecoveryContext(candidate.recovery)
      ? protectPendingAttendanceScan(restored)
      : existing;
  }
  const ownerUserId = stringValue(candidate.ownerUserId);
  const sessionId = stringValue(candidate.sessionId);
  const qrPayload = stringValue(candidate.qrPayload);
  const clientEventId = stringValue(candidate.clientEventId);
  const scannedAt = stringValue(candidate.scannedAt);
  const deviceId = stringValue(candidate.deviceId);
  const runtimeId = stringValue(candidate.runtimeId);
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
  const recovery = normalizeRecoveryContext(candidate.recovery);
  const legacy: PendingAttendanceScan = {
    id: attendanceQueueRowId(scanReference),
    scanReference,
    ownerUserId,
    ...(groupId ? { groupId } : {}),
    sessionId,
    qrPayload,
    clientEventId,
    scannedAt,
    deviceId,
    ...(runtimeId ? { runtimeId } : {}),
    queuedAt,
    attemptCount,
    nextAttemptAt,
    // Preserve a recent cross-tab delivery lease; recover a stale/crashed one.
    deliveryState: deliveryIsFresh ? "sending" : "pending",
    ...(deliveryIsFresh ? { deliveryStartedAt: legacyDeliveryStartedAt } : {}),
    ...(lastAttemptAt ? { lastAttemptAt } : {}),
    ...(recovery ? { recovery } : {}),
  };
  const protectedScan = await protectPendingAttendanceScan(legacy);
  const verified = await restorePendingAttendanceScan(protectedScan);
  if (verified.qrPayload !== legacy.qrPayload) {
    throw new Error("Attendance queue encryption verification failed.");
  }
  return protectedScan;
}

async function normalizeRejectedAttendanceScan(
  candidate: Record<string, unknown>,
): Promise<StoredRejectedAttendanceScan | null> {
  if (
    candidate.storageVersion === 5
    && (
      candidate.protectedRecovery === undefined
      || isProtectedBrowserValue(candidate.protectedRecovery)
    )
  ) {
    const existing = candidate as unknown as StoredRejectedAttendanceScan;
    const restored = await restoreRejectedAttendanceScan(existing);
    return normalizeRecoveryContext(candidate.recovery)
      ? protectRejectedAttendanceScan(restored)
      : existing;
  }
  const sanitized = await sanitizeLegacyRejectedAttendanceScan(candidate);
  if (!sanitized) return null;
  const recovery = normalizeRecoveryContext(candidate.recovery);
  const protectedScan = await protectRejectedAttendanceScan({
    ...sanitized,
    ...(recovery ? { recovery } : {}),
  });
  await restoreRejectedAttendanceScan(protectedScan);
  return protectedScan;
}

function replaceMigratedRows<T extends { id: string }>(
  store: IDBObjectStore,
  originals: Record<string, unknown>[],
  replacements: Array<T | null>,
) {
  originals.forEach((original, index) => {
    const oldId = stringValue(original.id);
    const replacement = replacements[index];
    // Invalid, corrupt, or unattributable legacy rows remain quarantined in
    // place. Delete an old key only after a verified replacement is available.
    if (replacement) {
      store.put(replacement);
      if (oldId && oldId !== replacement.id) store.delete(oldId);
    }
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

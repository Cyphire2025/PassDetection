import {
  protectPendingAttendanceScan,
  recoveryContext,
  restorePendingAttendanceScan,
} from "./attendance-queue-codec";
import {
  type AttendanceDiscardReason,
  AttendanceQueueCapacityError,
  type AttendanceScanInput,
  MAX_PENDING_ATTENDANCE_SCANS_PER_OWNER,
  type PendingAttendanceScan,
  type StoredPendingAttendanceScan,
  type StoredRejectedAttendanceScan,
} from "./attendance-queue-contracts";
import {
  createDiscardTombstone,
  syncAttendanceDiscardTombstones,
} from "./attendance-queue-discards";
import { getRetryAfterMs } from "./attendance-queue-errors";
import {
  OWNER_INDEX,
  PENDING_STORE_NAME,
  REJECTED_STORE_NAME,
  requestToPromise,
  transactionToPromise,
} from "./attendance-queue-idb";
import { attendanceQueueRowId, createAttendanceScanReference } from "./attendance-queue-privacy";
import {
  announceScheduleChanged,
  assertCurrentOwner,
  getCurrentUserId,
  requireCurrentUserId,
  withOwnerQueueLock,
} from "./attendance-queue-runtime";
import {
  listDiscardTombstonesForOwner,
  listPendingForOwner,
  listRejectedForOwner,
  openDb,
} from "./attendance-queue-storage";
import { attendanceRetryState, earliestAttendanceAttemptAt } from "./attendance-retry-policy";
import { authorizeBrowserOfflineScan } from "./browser-offline-authorization";
import { DISCARD_TOMBSTONE_STORE } from "./browser-offline-database";

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
      const pending = existing ? await restorePendingAttendanceScan(existing) : pendingScan;
      assertCurrentOwner(ownerUserId);
      announceScheduleChanged();
      return {
        pending,
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
  const scans = await listPendingForOwner(ownerUserId);
  assertCurrentOwner(ownerUserId);
  return scans;
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
  assertCurrentOwner(ownerUserId);
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

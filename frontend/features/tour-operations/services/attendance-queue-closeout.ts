import {
  type StoredPendingAttendanceScan,
  type StoredRejectedAttendanceScan,
} from "./attendance-queue-contracts";
import { createDiscardTombstone } from "./attendance-queue-discards";
import {
  OWNER_INDEX,
  PENDING_STORE_NAME,
  REJECTED_STORE_NAME,
  requestToPromise,
  transactionToPromise,
} from "./attendance-queue-idb";
import {
  announceScheduleChanged,
  assertAuthenticationSnapshotCurrent,
  assertCurrentOwner,
  requireCurrentUserId,
  withOwnerQueueLock,
} from "./attendance-queue-runtime";
import {
  type AttendanceQueueLogoutDisposition,
  type BrowserAttendanceQueueSafetySnapshot,
  hasUnsafeBrowserAttendanceQueue,
} from "./attendance-queue-safety-contract";
import {
  listDiscardTombstonesForOwner,
  listPendingForOwner,
  listRejectedForOwner,
  openDb,
} from "./attendance-queue-storage";
import {
  type AttendanceCloseoutQueueCounts,
  classifyAttendanceCloseoutQueue,
  earliestAttendanceAttemptAt,
} from "./attendance-retry-policy";
import { DISCARD_TOMBSTONE_STORE } from "./browser-offline-database";

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

export async function collectQueueCloseoutUnlocked(
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

export async function readQueueSafetySnapshot(
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
  // listPendingForOwner already returns the same ascending locale order.
  const oldestQueuedAt = pendingRows[0]?.queuedAt ?? null;
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

export async function purgeQueueForOwner(ownerUserId: string) {
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
        // An old unscoped row cannot be attributed safely. Explicit discard
        // preserves it instead of manufacturing incorrect audit data.
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

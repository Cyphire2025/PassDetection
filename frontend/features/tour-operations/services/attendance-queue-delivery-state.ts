import {
  protectRejectedAttendanceScan,
  restorePendingAttendanceScan,
} from "./attendance-queue-codec";
import {
  type PendingAttendanceScan,
  type StoredPendingAttendanceScan,
} from "./attendance-queue-contracts";
import { getRetryAfterMs } from "./attendance-queue-errors";
import {
  OWNER_INDEX,
  PENDING_STORE_NAME,
  REJECTED_STORE_NAME,
  requestToPromise,
  transactionToPromise,
} from "./attendance-queue-idb";
import { createRejectedAttendanceScan } from "./attendance-queue-privacy";
import { openDb } from "./attendance-queue-storage";
import { attendanceRetryState, isAttendanceAttemptEligible } from "./attendance-retry-policy";

export async function quarantineRejectedAttendanceScan(
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

export async function markPendingAttendanceRetry(
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

export async function claimPendingAttendanceDelivery(
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

export async function releasePendingAttendanceDelivery(id: string, ownerUserId: string) {
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

/** Recover an interrupted drain only while its cross-tab drain and owner locks are held. */
export async function recoverInterruptedAttendanceDeliveries(
  ownerUserId: string,
  verifiedScans: readonly PendingAttendanceScan[],
) {
  // A process-local fallback cannot prove that another tab stopped sending.
  if (typeof navigator === "undefined" || !navigator.locks?.request) return;
  const interruptedIds = new Set(verifiedScans
    .filter((scan) => scan.ownerUserId === ownerUserId && scan.deliveryState === "sending")
    .map((scan) => scan.id));
  if (interruptedIds.size === 0) return;
  const db = await openDb();
  try {
    const transaction = db.transaction(PENDING_STORE_NAME, "readwrite");
    const completion = transactionToPromise(transaction);
    const store = transaction.objectStore(PENDING_STORE_NAME);
    const rows = await requestToPromise<StoredPendingAttendanceScan[]>(
      store.index(OWNER_INDEX).getAll(ownerUserId),
    );
    for (const row of rows) {
      if (
        !interruptedIds.has(row.id)
        || row.ownerUserId !== ownerUserId
        || row.storageVersion !== 5
        || row.deliveryState !== "sending"
      ) continue;
      store.put({ ...row, deliveryState: "pending", deliveryStartedAt: undefined });
    }
    await completion;
  } finally {
    db.close();
  }
}

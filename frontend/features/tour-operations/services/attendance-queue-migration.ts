import {
  isProtectedBrowserValue,
  normalizeRecoveryContext,
  protectPendingAttendanceScan,
  protectRejectedAttendanceScan,
  restorePendingAttendanceScan,
  restoreRejectedAttendanceScan,
} from "./attendance-queue-codec";
import {
  type PendingAttendanceScan,
  type StoredPendingAttendanceScan,
  type StoredRejectedAttendanceScan,
} from "./attendance-queue-contracts";
import {
  PENDING_STORE_NAME,
  readAllUnknown,
  REJECTED_STORE_NAME,
  transactionToPromise,
} from "./attendance-queue-idb";
import {
  attendanceQueueRowId,
  createAttendanceScanReference,
  isAttendanceScanReference,
  sanitizeLegacyRejectedAttendanceScan,
} from "./attendance-queue-privacy";

export async function migrateLegacyQueueRecords(db: IDBDatabase) {
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

export async function normalizePendingAttendanceScan(
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

export async function normalizeRejectedAttendanceScan(
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

export function replaceMigratedRows<T extends { id: string }>(
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

export function normalizedIso(value: unknown, fallback: string) {
  const candidate = stringValue(value);
  return candidate && Number.isFinite(Date.parse(candidate)) ? candidate : fallback;
}

export function normalizedOptionalIso(value: unknown) {
  const candidate = stringValue(value);
  return candidate && Number.isFinite(Date.parse(candidate)) ? candidate : undefined;
}

export function stringValue(value: unknown) {
  return typeof value === "string" && value.length > 0 ? value : null;
}

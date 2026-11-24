import { PENDING_STORE_NAME, QR_PAYLOAD_PATTERN, REJECTED_STORE_NAME, STORAGE_KEY_ID } from './constants.js';
import { requestToPromise, transactionToPromise } from './idb-requests.js';
import {
  createScanReference,
  decryptProtectedJson,
  encryptProtectedJson,
  hashReference,
  pendingScanAssociatedData,
  readStoredCryptoKey,
} from './protected-storage.js';
import { isRecord, isScanReference, requiredString, validIso } from './values.js';

export async function migrateLegacyQueueRecords(database) {
  const [pendingRows, rejectedRows] = await Promise.all([
    readAllQueueRows(database, PENDING_STORE_NAME),
    readAllQueueRows(database, REJECTED_STORE_NAME),
  ]);
  const [pendingReplacements, rejectedReplacements] = await Promise.all([
    Promise.all(pendingRows.map((row) => normalizePendingQueueRow(row, database).catch(() => null))),
    Promise.all(rejectedRows.map((row) => sanitizeRejectedQueueRow(row).catch(() => null))),
  ]);
  const transaction = database.transaction(
    [PENDING_STORE_NAME, REJECTED_STORE_NAME],
    "readwrite",
  );
  const completion = transactionToPromise(transaction);
  replaceQueueRows(
    transaction.objectStore(PENDING_STORE_NAME),
    pendingRows,
    pendingReplacements,
  );
  replaceQueueRows(
    transaction.objectStore(REJECTED_STORE_NAME),
    rejectedRows,
    rejectedReplacements,
  );
  await completion;
}

export async function normalizePendingQueueRow(candidate, database) {
  if (!isRecord(candidate)) return null;
  if (candidate.storageVersion === 5 && isRecord(candidate.protectedQrPayload)) {
    const storageKey = await readStoredCryptoKey(database, STORAGE_KEY_ID);
    const decrypted = await decryptProtectedJson(
      storageKey,
      candidate.protectedQrPayload,
      pendingScanAssociatedData(candidate),
    );
    if (!isRecord(decrypted) || !QR_PAYLOAD_PATTERN.test(decrypted.qrPayload)) {
      throw new Error("Protected attendance queue row is corrupt.");
    }
    const expected = await createScanReference({
      ownerUserId: candidate.ownerUserId,
      groupId: candidate.groupId,
      sessionId: candidate.sessionId,
      qrPayload: decrypted.qrPayload,
    });
    if (expected !== candidate.scanReference) throw new Error("Protected queue identity failed.");
    return candidate;
  }
  const ownerId = requiredString(candidate.ownerUserId);
  const sessionId = requiredString(candidate.sessionId);
  const qrPayload = requiredString(candidate.qrPayload);
  const clientEventId = requiredString(candidate.clientEventId);
  const scannedAt = requiredString(candidate.scannedAt);
  const deviceId = requiredString(candidate.deviceId);
  const queuedAt = requiredString(candidate.queuedAt);
  if (!ownerId || !sessionId || !qrPayload || !clientEventId || !scannedAt || !deviceId || !queuedAt) {
    return null;
  }
  const groupId = requiredString(candidate.groupId);
  const scanReference = isScanReference(candidate.scanReference)
    ? candidate.scanReference
    : await createScanReference({
        ownerUserId: ownerId,
        groupId,
        sessionId,
        qrPayload,
      });
  const nextAttemptAt = validIso(candidate.nextAttemptAt) || queuedAt;
  const lastAttemptAt = validIso(candidate.lastAttemptAt);
  const metadata = {
    id: `attendance-scan:${scanReference}`,
    scanReference,
    ownerUserId: ownerId,
    ...(groupId ? { groupId } : {}),
    sessionId,
    clientEventId,
    scannedAt,
    deviceId,
    queuedAt,
    attemptCount: Number.isFinite(candidate.attemptCount)
      ? Math.max(0, Math.trunc(candidate.attemptCount))
      : 0,
    nextAttemptAt,
    deliveryState: candidate.deliveryState === "sending" ? "sending" : "pending",
    ...(lastAttemptAt ? { lastAttemptAt } : {}),
  };
  const storageKey = await readStoredCryptoKey(database, STORAGE_KEY_ID);
  const protectedQrPayload = await encryptProtectedJson(
    storageKey,
    { qrPayload },
    pendingScanAssociatedData(metadata),
  );
  const verified = await decryptProtectedJson(
    storageKey,
    protectedQrPayload,
    pendingScanAssociatedData(metadata),
  );
  if (!isRecord(verified) || verified.qrPayload !== qrPayload) {
    throw new Error("Legacy queue encryption verification failed.");
  }
  return { ...metadata, protectedQrPayload, storageVersion: 5 };
}

export async function sanitizeRejectedQueueRow(candidate) {
  if (!isRecord(candidate)) return null;
  const ownerId = requiredString(candidate.ownerUserId);
  const sessionId = requiredString(candidate.sessionId);
  const clientEventId = requiredString(candidate.clientEventId);
  const scannedAt = requiredString(candidate.scannedAt);
  const deviceId = requiredString(candidate.deviceId);
  const queuedAt = requiredString(candidate.queuedAt);
  const rejectedAt = requiredString(candidate.rejectedAt);
  const errorCode = requiredString(candidate.errorCode);
  if (!ownerId || !sessionId || !clientEventId || !scannedAt || !deviceId || !queuedAt || !rejectedAt || !errorCode) {
    return null;
  }
  const groupId = requiredString(candidate.groupId);
  const qrPayload = requiredString(candidate.qrPayload);
  const scanReference = isScanReference(candidate.scanReference)
    ? candidate.scanReference
    : qrPayload
      ? await createScanReference({
          ownerUserId: ownerId,
          groupId,
          sessionId,
          qrPayload,
        })
      : await hashReference([
          "attendance-terminal-v4",
          ownerId,
          groupId || "legacy-group",
          sessionId,
          clientEventId,
          requiredString(candidate.id) || "missing-id",
        ]);
  return {
    id: `attendance-rejected:${scanReference}`,
    scanReference,
    ownerUserId: ownerId,
    ...(groupId ? { groupId } : {}),
    sessionId,
    clientEventId,
    scannedAt,
    deviceId,
    queuedAt,
    rejectedAt,
    errorCode,
  };
}

export function readAllQueueRows(database, storeName) {
  const store = database.transaction(storeName, "readonly").objectStore(storeName);
  return requestToPromise(store.getAll());
}

export function replaceQueueRows(store, originals, replacements) {
  originals.forEach((original, index) => {
    const oldId = isRecord(original) ? requiredString(original.id) : null;
    const replacement = replacements[index];
    if (replacement) {
      store.put(replacement);
      if (oldId && oldId !== replacement.id) store.delete(oldId);
    }
  });
}

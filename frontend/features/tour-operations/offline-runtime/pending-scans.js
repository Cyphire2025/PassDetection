import { MAX_PENDING_SCANS_PER_OWNER, OWNER_INDEX, PENDING_STORE_NAME, STORAGE_KEY_ID } from './constants.js';
import { openQueueDatabase } from './database.js';
import { requestToPromise, transactionToPromise } from './idb-requests.js';
import { createScanReference, encryptProtectedJson, pendingScanAssociatedData, readStoredCryptoKey } from './protected-storage.js';
import { createClientEventId, readCurrentOwner } from './values.js';

export function createPendingScanQueue(authorizations) {
  async function enqueueScan(selection) {
    if (readCurrentOwner() !== selection.ownerUserId) {
      throw new Error("The signed-in coordinator changed.");
    }
    const authorization = await authorizations.authorizeDecodedScan(
      selection.groupId,
      selection.sessionId,
      selection.qrPayload,
    );
    const scanReference = await createScanReference(selection);
    const stableId = `attendance-scan:${scanReference}`;
    const timestamp = authorization.scannedAt;
    const recovery = {
      passengerId: authorization.passengerId,
      passengerLabel: authorization.passengerLabel,
      sessionLabel: authorization.sessionLabel,
    };
    const pendingMetadata = {
      groupId: selection.groupId,
      sessionId: selection.sessionId,
      clientEventId: createClientEventId(),
      scannedAt: timestamp,
      deviceId: authorization.runtimeId,
      runtimeId: authorization.runtimeId,
      id: stableId,
      scanReference,
      ownerUserId: selection.ownerUserId,
      queuedAt: timestamp,
      attemptCount: 0,
      nextAttemptAt: timestamp,
      deliveryState: "pending",
    };
  
    const db = await openQueueDatabase();
    try {
      if (readCurrentOwner() !== selection.ownerUserId) {
        throw new Error("The signed-in coordinator changed.");
      }
      const storageKey = await readStoredCryptoKey(db, STORAGE_KEY_ID);
      const protectedQrPayload = await encryptProtectedJson(
        storageKey,
        { qrPayload: selection.qrPayload, recovery },
        pendingScanAssociatedData(pendingMetadata),
      );
      if (readCurrentOwner() !== selection.ownerUserId) {
        throw new Error("The signed-in coordinator changed.");
      }
      const transaction = db.transaction(PENDING_STORE_NAME, "readwrite");
      const completion = transactionToPromise(transaction);
      const store = transaction.objectStore(PENDING_STORE_NAME);
      try {
        const existing = await requestToPromise(store.get(stableId));
        if (!existing) {
          const ownerRowCount = await requestToPromise(
            store.index(OWNER_INDEX).count(selection.ownerUserId),
          );
          if (ownerRowCount >= MAX_PENDING_SCANS_PER_OWNER) {
            throw new Error("Offline attendance storage reached its safe device limit.");
          }
          if (readCurrentOwner() !== selection.ownerUserId) {
            throw new Error("The signed-in coordinator changed.");
          }
          await requestToPromise(store.put({
            ...pendingMetadata,
            protectedQrPayload,
            storageVersion: 5,
          }));
        }
        await completion;
        return { duplicate: Boolean(existing) };
      } catch (error) {
        await completion.catch(() => undefined);
        throw error;
      }
    } finally {
      db.close();
    }
  }

  return { enqueueScan };
}

import { verifyStoredAuthorization } from './authorization-validation.js';
import { AUTHORIZATION_STORE_NAME, STORAGE_KEY_ID } from './constants.js';
import { openQueueDatabase } from './database.js';
import { requestToPromise, transactionToPromise } from './idb-requests.js';
import { decryptProtectedJson, readStoredCryptoKey, sha256HexBytes } from './protected-storage.js';
import { resolveAuthorizationTrustedTime } from './trusted-time.js';
import { isRecord, parseRequiredInstant, readCurrentOwner, requiredString } from './values.js';

export function createOfflineAuthorization() {
  let authorizationByGroup = new Map();

  async function readAuthorizedCoordinatorSelections(ownerId, requestedGroupId) {
    const database = await openQueueDatabase();
    try {
      const authorizationRows = await requestToPromise(
        database.transaction(AUTHORIZATION_STORE_NAME, "readonly")
          .objectStore(AUTHORIZATION_STORE_NAME)
          .getAll(),
      );
      const storageKey = await readStoredCryptoKey(database, STORAGE_KEY_ID);
      const verified = [];
      for (const record of authorizationRows) {
        if (!isRecord(record) || record.ownerUserId !== ownerId) continue;
        try {
          const id = requiredString(record.id);
          if (!id || !isRecord(record.protectedValue)) continue;
          const storedValue = await decryptProtectedJson(
            storageKey,
            record.protectedValue,
            `coordinator-offline-authorization|${id}`,
          );
          const authorization = await verifyStoredAuthorization(database, record, storedValue);
          resolveAuthorizationTrustedTime(authorization);
          verified.push(authorization);
        } catch {
          // One corrupt or expired manifest must not make another independently
          // signed group unavailable.
        }
      }
      authorizationByGroup = new Map(
        verified.map((item) => [item.payload.group_id, item]),
      );
      const groups = verified.map((item) => ({
        id: item.payload.group_id,
        name: item.payload.group_label,
      }));
      const sessionsByGroup = new Map(
        verified.map((item) => [
          item.payload.group_id,
          item.payload.sessions.map((session) => ({
            id: session.id,
            groupId: item.payload.group_id,
            name: session.label,
            status: session.status,
          })),
        ]),
      );
      if (requestedGroupId && !authorizationByGroup.has(requestedGroupId)) {
        return { groups: [], sessionsByGroup: new Map() };
      }
      return { groups, sessionsByGroup };
    } finally {
      database.close();
    }
  }

  async function authorizeDecodedScan(groupId, sessionId, qrPayload) {
    const authorization = authorizationByGroup.get(groupId);
    if (!authorization) throw new Error("No signed roster is available for this group.");
    const trustedNow = resolveAuthorizationTrustedTime(authorization);
    const session = authorization.payload.sessions.find((item) => item.id === sessionId);
    if (!session) throw new Error("This activity is not in the signed offline authorization.");
    if (
      trustedNow < parseRequiredInstant(session.scheduled_starts_at) - 5 * 60_000
      || trustedNow > parseRequiredInstant(session.scheduled_ends_at)
    ) {
      throw new Error("This activity is outside its signed attendance window.");
    }
    const tokenHash = await sha256HexBytes(new TextEncoder().encode(qrPayload));
    const matches = authorization.payload.passengers.filter((item) => item.token_hash === tokenHash);
    if (matches.length !== 1) throw new Error("This QR is not in the signed roster for this group.");
    const passenger = matches[0];
    if (trustedNow > parseRequiredInstant(passenger.token_valid_until)) {
      throw new Error("This passenger's signed QR evidence expired.");
    }
    await persistAuthorizationTrustedHighWater(authorization, trustedNow);
    return {
      runtimeId: authorization.runtimeId,
      passengerId: passenger.id,
      passengerLabel: passenger.label,
      scannedAt: new Date(trustedNow).toISOString(),
      sessionLabel: session.label,
    };
  }

  async function persistAuthorizationTrustedHighWater(authorization, trustedNow) {
    if (readCurrentOwner() !== authorization.record.ownerUserId) {
      throw new Error("The signed-in coordinator changed.");
    }
    const database = await openQueueDatabase();
    try {
      const transaction = database.transaction(AUTHORIZATION_STORE_NAME, "readwrite");
      const completion = transactionToPromise(transaction);
      const store = transaction.objectStore(AUTHORIZATION_STORE_NAME);
      const current = await requestToPromise(store.get(authorization.record.id));
      if (
        !isRecord(current)
        || current.ownerUserId !== authorization.record.ownerUserId
        || current.groupId !== authorization.record.groupId
      ) {
        transaction.abort();
        await completion.catch(() => undefined);
        throw new Error("Signed authorization ownership changed.");
      }
      const currentHighWater = Number(current.trustedHighWaterMs);
      if (!Number.isFinite(currentHighWater) || trustedNow > currentHighWater) {
        const updated = { ...current, trustedHighWaterMs: Math.trunc(trustedNow) };
        store.put(updated);
        authorization.record = updated;
      }
      await completion;
    } finally {
      database.close();
    }
  }

  function clearAuthorizations() {
    authorizationByGroup.clear();
  }

  return { readAuthorizedCoordinatorSelections, authorizeDecodedScan, clearAuthorizations };
}

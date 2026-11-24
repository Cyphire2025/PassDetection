import { CRYPTO_KEY_STORE_NAME } from './constants.js';
import { requestToPromise } from './idb-requests.js';
import { decodeBase64url, readStoredCryptoKey, sha256HexBytes } from './protected-storage.js';
import { createAuthorizationRuntimeAnchor } from './trusted-time.js';
import { isRecord, isUuid, parseRequiredInstant, requiredString } from './values.js';

export async function verifyStoredAuthorization(database, record, storedValue) {
  if (!isRecord(storedValue) || !isRecord(storedValue.bundle) || !isRecord(storedValue.payload)) {
    throw new Error("Signed authorization storage is invalid.");
  }
  const bundle = storedValue.bundle;
  const payloadBytes = decodeBase64url(requiredString(bundle.payload), 2 * 1024 * 1024);
  const signature = decodeBase64url(requiredString(bundle.signature), 64);
  const publicKey = decodeBase64url(requiredString(bundle.public_key), 32);
  const keyId = requiredString(bundle.key_id);
  const runtimeId = requiredString(record.runtimeId);
  if (
    !keyId
    || signature.length !== 64
    || publicKey.length !== 32
    || !isUuid(runtimeId)
    || !["pwa", "webview"].includes(record.runtimeKind)
    || parseRequiredInstant(record.runtimeExpiresAt) <= Date.now()
  ) {
    throw new Error("Signed authorization shape is invalid.");
  }
  const pinned = await readStoredCryptoKey(
    database,
    `offline-verification-key:${keyId}`,
  );
  const pinnedRecord = await requestToPromise(
    database.transaction(CRYPTO_KEY_STORE_NAME, "readonly")
      .objectStore(CRYPTO_KEY_STORE_NAME)
      .get(`offline-verification-key:${keyId}`),
  );
  if (!isRecord(pinnedRecord) || pinnedRecord.digest !== await sha256HexBytes(publicKey)) {
    throw new Error("Signed authorization key changed.");
  }
  const signatureValid = await window.crypto.subtle.verify(
    { name: "Ed25519" },
    pinned,
    signature,
    payloadBytes,
  );
  if (!signatureValid) throw new Error("Signed authorization signature is invalid.");
  const payload = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(payloadBytes));
  validateAuthorizationPayload(payload, record, keyId);
  return {
    bundle,
    payload,
    record,
    runtimeId,
    runtime: createAuthorizationRuntimeAnchor(record, payload),
  };
}

export function validateAuthorizationPayload(payload, record, keyId) {
  if (
    !isRecord(payload)
    || payload.schema_version !== 1
    || payload.key_id !== keyId
    || payload.coordinator_user_id !== record.ownerUserId
    || payload.tenant_id !== record.agencyId
    || payload.group_id !== record.groupId
    || !isUuid(payload.group_id)
    || !requiredString(payload.group_label)
    || !Array.isArray(payload.sessions)
    || !Array.isArray(payload.passengers)
    || payload.sessions.length < 1
    || payload.sessions.length > 200
    || payload.passengers.length > 2000
  ) {
    throw new Error("Signed authorization binding is invalid.");
  }
  const serverTime = parseRequiredInstant(payload.server_time);
  const issuedAt = parseRequiredInstant(payload.issued_at);
  const notBefore = parseRequiredInstant(payload.not_before);
  const expiresAt = parseRequiredInstant(payload.expires_at);
  const maxSuspensionSeconds = Number(payload.max_suspension_seconds);
  if (
    issuedAt > serverTime
    || notBefore > serverTime + 2 * 60_000
    || expiresAt <= serverTime
    || !Number.isSafeInteger(maxSuspensionSeconds)
    || maxSuspensionSeconds < 60
    || maxSuspensionSeconds > 7 * 24 * 60 * 60
    || expiresAt - serverTime > maxSuspensionSeconds * 1000
  ) {
    throw new Error("Signed authorization time bounds are invalid.");
  }
  const sessionIds = new Set();
  for (const session of payload.sessions) {
    if (
      !isRecord(session)
      || !isUuid(session.id)
      || session.status !== "active"
      || !requiredString(session.label)
      || sessionIds.has(session.id)
      || parseRequiredInstant(session.scheduled_ends_at)
        <= parseRequiredInstant(session.scheduled_starts_at)
    ) {
      throw new Error("Signed attendance activity is invalid.");
    }
    sessionIds.add(session.id);
  }
  const passengerIds = new Set();
  const tokenHashes = new Set();
  for (const passenger of payload.passengers) {
    if (
      !isRecord(passenger)
      || !isUuid(passenger.id)
      || !requiredString(passenger.label)
      || typeof passenger.token_hash !== "string"
      || !/^[0-9a-f]{64}$/.test(passenger.token_hash)
      || passengerIds.has(passenger.id)
      || tokenHashes.has(passenger.token_hash)
    ) {
      throw new Error("Signed passenger evidence is invalid.");
    }
    parseRequiredInstant(passenger.token_valid_until);
    passengerIds.add(passenger.id);
    tokenHashes.add(passenger.token_hash);
  }
}

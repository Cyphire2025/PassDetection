import { CRYPTO_KEY_STORE_NAME, STORAGE_KEY_ID } from './constants.js';
import { requestToPromise } from './idb-requests.js';
import { isRecord } from './values.js';

export async function createScanReference(selection) {
  return hashReference([
    "attendance-scan-v4",
    selection.ownerUserId,
    selection.groupId || "legacy-group",
    selection.sessionId,
    selection.qrPayload,
  ]);
}

export async function hashReference(parts) {
  if (!window.crypto?.subtle) {
    throw new Error("Secure SHA-256 support is required for offline attendance storage.");
  }
  const digest = await window.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(JSON.stringify(parts)),
  );
  const hex = Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0")
  ).join("");
  return `sha256:${hex}`;
}

export async function sha256HexBytes(bytes) {
  const digest = await window.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0")
  ).join("");
}

export function pendingScanAssociatedData(scan) {
  return JSON.stringify([
    "attendance-pending-v5",
    scan.id,
    scan.ownerUserId,
    scan.groupId || "legacy-group",
    scan.sessionId,
  ]);
}

export async function readStoredCryptoKey(database, id) {
  const record = await requestToPromise(
    database.transaction(CRYPTO_KEY_STORE_NAME, "readonly")
      .objectStore(CRYPTO_KEY_STORE_NAME)
      .get(id),
  );
  if (!isRecord(record) || !record.key || record.key.extractable !== false) {
    throw new Error("The protected offline key is unavailable.");
  }
  return record.key;
}

export async function encryptProtectedJson(key, value, associatedData) {
  const plaintext = new TextEncoder().encode(JSON.stringify(value));
  const iv = window.crypto.getRandomValues(new Uint8Array(12));
  try {
    const ciphertext = await window.crypto.subtle.encrypt(
      {
        name: "AES-GCM",
        iv,
        additionalData: new TextEncoder().encode(associatedData),
        tagLength: 128,
      },
      key,
      plaintext,
    );
    return {
      algorithm: "AES-GCM",
      ciphertext,
      iv,
      keyId: STORAGE_KEY_ID,
      version: 1,
    };
  } finally {
    plaintext.fill(0);
  }
}

export async function decryptProtectedJson(key, envelope, associatedData) {
  if (
    !isRecord(envelope)
    || envelope.version !== 1
    || envelope.algorithm !== "AES-GCM"
    || envelope.keyId !== STORAGE_KEY_ID
    || !(envelope.ciphertext instanceof ArrayBuffer)
    || !(envelope.iv instanceof Uint8Array)
    || envelope.iv.length !== 12
  ) {
    throw new Error("Protected offline data is invalid.");
  }
  const plaintext = new Uint8Array(await window.crypto.subtle.decrypt(
    {
      name: "AES-GCM",
      iv: envelope.iv,
      additionalData: new TextEncoder().encode(associatedData),
      tagLength: 128,
    },
    key,
    envelope.ciphertext,
  ));
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(plaintext));
  } finally {
    plaintext.fill(0);
  }
}

export function decodeBase64url(value, maxBytes) {
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]+$/.test(value)) {
    throw new Error("Signed data is not canonical base64url.");
  }
  const padding = "=".repeat((4 - value.length % 4) % 4);
  const decoded = window.atob(value.replace(/-/g, "+").replace(/_/g, "/") + padding);
  if (decoded.length === 0 || decoded.length > maxBytes) {
    throw new Error("Signed data exceeds its bounded size.");
  }
  return Uint8Array.from(decoded, (character) => character.charCodeAt(0));
}


import {
  OFFLINE_CRYPTO_KEY_STORE,
  idbRequest,
  idbTransaction,
  openBrowserOfflineDatabase,
} from "./browser-offline-database";

const STORAGE_KEY_ID = "coordinator-offline-aes-gcm-v1";
const MAX_PROTECTED_JSON_BYTES = 2 * 1024 * 1024;

export type ProtectedBrowserValue = Readonly<{
  algorithm: "AES-GCM";
  ciphertext: ArrayBuffer;
  iv: Uint8Array<ArrayBuffer>;
  keyId: typeof STORAGE_KEY_ID;
  version: 1;
}>;

type StoredCryptoKey = Readonly<{
  createdAt: string;
  id: typeof STORAGE_KEY_ID;
  key: CryptoKey;
}>;

export async function protectBrowserJson(
  value: unknown,
  associatedData: string,
): Promise<ProtectedBrowserValue> {
  requireBrowserCrypto();
  const plaintext = new TextEncoder().encode(JSON.stringify(value));
  if (plaintext.byteLength === 0 || plaintext.byteLength > MAX_PROTECTED_JSON_BYTES) {
    plaintext.fill(0);
    throw new Error("Protected coordinator data exceeds the browser storage limit.");
  }
  const iv = crypto.getRandomValues(new Uint8Array(12));
  try {
    const key = await getOrCreateStorageKey();
    const ciphertext = await crypto.subtle.encrypt(
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

export async function unprotectBrowserJson<T>(
  envelope: ProtectedBrowserValue,
  associatedData: string,
): Promise<T> {
  requireBrowserCrypto();
  if (
    envelope.version !== 1
    || envelope.algorithm !== "AES-GCM"
    || envelope.keyId !== STORAGE_KEY_ID
    || !(envelope.ciphertext instanceof ArrayBuffer)
    || !(envelope.iv instanceof Uint8Array)
    || envelope.iv.byteLength !== 12
    || envelope.ciphertext.byteLength < 16
    || envelope.ciphertext.byteLength > MAX_PROTECTED_JSON_BYTES + 16
  ) {
    throw new Error("Protected coordinator data has an unsupported format.");
  }
  const key = await getExistingStorageKey();
  const plaintext = new Uint8Array(await crypto.subtle.decrypt(
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
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(plaintext)) as T;
  } finally {
    plaintext.fill(0);
  }
}

async function getOrCreateStorageKey(): Promise<CryptoKey> {
  const candidate = await crypto.subtle.generateKey(
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
  const database = await openBrowserOfflineDatabase();
  try {
    // IndexedDB serializes readwrite transactions on this store. Generating the
    // candidate before the transaction avoids transaction auto-commit while
    // still ensuring two tabs cannot replace one another's selected key.
    const transaction = database.transaction(OFFLINE_CRYPTO_KEY_STORE, "readwrite");
    const completion = idbTransaction(transaction);
    const store = transaction.objectStore(OFFLINE_CRYPTO_KEY_STORE);
    const existing = await idbRequest<StoredCryptoKey | undefined>(store.get(STORAGE_KEY_ID));
    if (!existing) {
      store.add({ id: STORAGE_KEY_ID, key: candidate, createdAt: new Date().toISOString() });
    }
    await completion;
    return existing?.key ?? candidate;
  } finally {
    database.close();
  }
}

async function getExistingStorageKey(): Promise<CryptoKey> {
  const database = await openBrowserOfflineDatabase();
  try {
    const store = database.transaction(OFFLINE_CRYPTO_KEY_STORE, "readonly")
      .objectStore(OFFLINE_CRYPTO_KEY_STORE);
    const record = await idbRequest<StoredCryptoKey | undefined>(store.get(STORAGE_KEY_ID));
    if (!record?.key || record.key.extractable) {
      throw new Error("The non-exportable coordinator storage key is unavailable.");
    }
    return record.key;
  } finally {
    database.close();
  }
}

function requireBrowserCrypto() {
  if (typeof crypto === "undefined" || !crypto.subtle || !crypto.getRandomValues) {
    throw new Error("Web Crypto is required for coordinator offline storage.");
  }
}

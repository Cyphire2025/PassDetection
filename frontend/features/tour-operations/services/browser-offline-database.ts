
export const BROWSER_OFFLINE_DB_NAME = "passdetection-tour-ops";
export const BROWSER_OFFLINE_DB_VERSION = 5;

export const PENDING_ATTENDANCE_STORE = "pending-attendance-scans";
export const REJECTED_ATTENDANCE_STORE = "rejected-attendance-scans";
export const DISCARD_TOMBSTONE_STORE = "attendance-discard-tombstones";
export const OFFLINE_SNAPSHOT_STORE = "coordinator-offline-snapshots";
export const OFFLINE_AUTHORIZATION_STORE = "coordinator-offline-authorizations";
export const OFFLINE_CRYPTO_KEY_STORE = "offline-crypto-keys";

export const OWNER_USER_ID_INDEX = "owner-user-id";
export const EXPIRES_AT_INDEX = "expires-at";
export const SYNC_STATE_INDEX = "sync-state";

/**
 * Opens the one coordinator-owned IndexedDB database without ever deleting a
 * legacy queue. Records that predate owner scoping remain quarantined in place
 * until an explicit, attributable migration can copy and verify them.
 */
export function openBrowserOfflineDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(BROWSER_OFFLINE_DB_NAME, BROWSER_OFFLINE_DB_VERSION);
    request.onupgradeneeded = () => upgradeBrowserOfflineDatabase(request);
    request.onsuccess = () => {
      const database = request.result;
      database.onversionchange = () => database.close();
      resolve(database);
    };
    request.onerror = () => reject(
      request.error ?? new Error("Coordinator offline database could not be opened."),
    );
    request.onblocked = () => reject(
      new Error("Coordinator offline database upgrade is blocked by another tab."),
    );
  });
}

function upgradeBrowserOfflineDatabase(request: IDBOpenDBRequest) {
  const database = request.result;
  const transaction = request.transaction;
  if (!transaction) throw new Error("Coordinator offline upgrade transaction is unavailable.");

  // Never delete the v1 unscoped store. Its rows are not automatically
  // attributable to the currently signed-in account, but loss is worse than a
  // quarantined legacy row. The v5 privacy migration only replaces a row after
  // it has an owner and its encrypted replacement was verified in memory.
  ensureOwnerStore(database, transaction, PENDING_ATTENDANCE_STORE);
  ensureOwnerStore(database, transaction, REJECTED_ATTENDANCE_STORE);
  ensureOwnerStore(database, transaction, DISCARD_TOMBSTONE_STORE, true);

  const snapshots = ensureKeyedStore(database, transaction, OFFLINE_SNAPSHOT_STORE);
  ensureIndex(snapshots, OWNER_USER_ID_INDEX, "ownerUserId");
  ensureIndex(snapshots, EXPIRES_AT_INDEX, "expiresAt");

  const authorizations = ensureKeyedStore(
    database,
    transaction,
    OFFLINE_AUTHORIZATION_STORE,
  );
  ensureIndex(authorizations, OWNER_USER_ID_INDEX, "ownerUserId");
  ensureIndex(authorizations, EXPIRES_AT_INDEX, "expiresAt");

  if (!database.objectStoreNames.contains(OFFLINE_CRYPTO_KEY_STORE)) {
    database.createObjectStore(OFFLINE_CRYPTO_KEY_STORE, { keyPath: "id" });
  }
}

function ensureOwnerStore(
  database: IDBDatabase,
  transaction: IDBTransaction,
  storeName: string,
  includeSyncState = false,
) {
  const store = ensureKeyedStore(database, transaction, storeName);
  ensureIndex(store, OWNER_USER_ID_INDEX, "ownerUserId");
  if (includeSyncState) ensureIndex(store, SYNC_STATE_INDEX, "syncState");
  return store;
}

function ensureKeyedStore(
  database: IDBDatabase,
  transaction: IDBTransaction,
  storeName: string,
) {
  return database.objectStoreNames.contains(storeName)
    ? transaction.objectStore(storeName)
    : database.createObjectStore(storeName, { keyPath: "id" });
}

function ensureIndex(store: IDBObjectStore, name: string, keyPath: string) {
  if (!store.indexNames.contains(name)) {
    store.createIndex(name, keyPath, { unique: false });
  }
}

export function idbRequest<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("IndexedDB request failed."));
  });
}

export function idbTransaction(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(
      transaction.error ?? new Error("IndexedDB transaction failed."),
    );
    transaction.onabort = () => reject(
      transaction.error ?? new Error("IndexedDB transaction was aborted."),
    );
  });
}

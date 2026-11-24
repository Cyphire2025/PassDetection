import {
  AUTHORIZATION_STORE_NAME,
  CRYPTO_KEY_STORE_NAME,
  DB_NAME,
  DB_VERSION,
  DISCARD_STORE_NAME,
  OWNER_INDEX,
  PENDING_STORE_NAME,
  REJECTED_STORE_NAME,
  SNAPSHOT_STORE_NAME,
} from './constants.js';
import { migrateLegacyQueueRecords } from './queue-migration.js';

let privacyMigrationPromise = null;

export function openQueueDatabase() {
  return new Promise((resolve, reject) => {
    const request = window.indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      const upgrade = request.transaction;
      if (!upgrade) return;
      // Never delete an unscoped legacy queue. Unattributable rows remain
      // quarantined until the online application can reconcile them.
      ensureOwnerScopedStore(database, upgrade, PENDING_STORE_NAME);
      ensureOwnerScopedStore(database, upgrade, REJECTED_STORE_NAME);
      ensureOwnerScopedStore(database, upgrade, DISCARD_STORE_NAME);
      ensureOwnerScopedStore(database, upgrade, SNAPSHOT_STORE_NAME);
      const authorizationStore = ensureOwnerScopedStore(
        database,
        upgrade,
        AUTHORIZATION_STORE_NAME,
      );
      if (!authorizationStore.indexNames.contains("expires-at")) {
        authorizationStore.createIndex("expires-at", "expiresAt", { unique: false });
      }
      const snapshotStore = upgrade.objectStore(SNAPSHOT_STORE_NAME);
      if (!snapshotStore.indexNames.contains("expires-at")) {
        snapshotStore.createIndex("expires-at", "expiresAt", { unique: false });
      }
      const discardStore = upgrade.objectStore(DISCARD_STORE_NAME);
      if (!discardStore.indexNames.contains("sync-state")) {
        discardStore.createIndex("sync-state", "syncState", { unique: false });
      }
      if (!database.objectStoreNames.contains(CRYPTO_KEY_STORE_NAME)) {
        database.createObjectStore(CRYPTO_KEY_STORE_NAME, { keyPath: "id" });
      }
    };
    request.onsuccess = () => {
      const database = request.result;
      database.onversionchange = () => database.close();
      const migration = privacyMigrationPromise ??=
        migrateLegacyQueueRecords(database).catch((error) => {
          privacyMigrationPromise = null;
          throw error;
        });
      migration.then(() => resolve(database)).catch((error) => {
        database.close();
        reject(error);
      });
    };
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error("Offline scan database is busy."));
  });
}

export function ensureOwnerScopedStore(database, upgrade, storeName) {
  const store = database.objectStoreNames.contains(storeName)
    ? upgrade.objectStore(storeName)
    : database.createObjectStore(storeName, { keyPath: "id" });
  if (!store.indexNames.contains(OWNER_INDEX)) {
    store.createIndex(OWNER_INDEX, "ownerUserId", { unique: false });
  }
  return store;
}

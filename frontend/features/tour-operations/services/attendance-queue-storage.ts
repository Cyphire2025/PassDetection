import {
  restorePendingAttendanceScan,
  restoreRejectedAttendanceScan,
} from "./attendance-queue-codec";
import {
  type AttendanceDiscardTombstone,
  type StoredPendingAttendanceScan,
  type StoredRejectedAttendanceScan,
} from "./attendance-queue-contracts";
import {
  OWNER_INDEX,
  PENDING_STORE_NAME,
  REJECTED_STORE_NAME,
  requestToPromise,
  transactionToPromise,
} from "./attendance-queue-idb";
import { migrateLegacyQueueRecords } from "./attendance-queue-migration";
import { MIGRATION_LOCK, withBrowserLock } from "./attendance-queue-runtime";
import { DISCARD_TOMBSTONE_STORE, openBrowserOfflineDatabase } from "./browser-offline-database";

export const SYNCHRONIZED_DISCARD_RETENTION_MS = 30 * 24 * 60 * 60 * 1_000;

export let privacyMigrationPromise: Promise<void> | null = null;

/** Return verified owner rows in ascending queuedAt locale order. */
export async function listPendingForOwner(ownerUserId: string) {
  const db = await openDb();
  try {
    const store = db.transaction(PENDING_STORE_NAME, "readonly")
      .objectStore(PENDING_STORE_NAME);
    const storedScans = await requestToPromise<StoredPendingAttendanceScan[]>(
      store.index(OWNER_INDEX).getAll(ownerUserId),
    );
    const scans = await Promise.all(storedScans.map(restorePendingAttendanceScan));
    return scans.sort((left, right) => left.queuedAt.localeCompare(right.queuedAt));
  } finally {
    db.close();
  }
}

export async function listRejectedForOwner(ownerUserId: string) {
  const db = await openDb();
  try {
    const store = db.transaction(REJECTED_STORE_NAME, "readonly")
      .objectStore(REJECTED_STORE_NAME);
    const storedScans = await requestToPromise<StoredRejectedAttendanceScan[]>(
      store.index(OWNER_INDEX).getAll(ownerUserId),
    );
    return Promise.all(storedScans.map(restoreRejectedAttendanceScan));
  } finally {
    db.close();
  }
}

export async function removePendingForOwner(id: string, ownerUserId: string) {
  const db = await openDb();
  try {
    const transaction = db.transaction(PENDING_STORE_NAME, "readwrite");
    const completion = transactionToPromise(transaction);
    const store = transaction.objectStore(PENDING_STORE_NAME);
    const existing = await requestToPromise<StoredPendingAttendanceScan | undefined>(
      store.get(id),
    );
    if (existing?.ownerUserId === ownerUserId) store.delete(id);
    await completion;
  } finally {
    db.close();
  }
}

export async function openDb() {
  const database = await openBrowserOfflineDatabase();
  const migration = privacyMigrationPromise ??= withBrowserLock(
    MIGRATION_LOCK,
    () => migrateLegacyQueueRecords(database),
  ).catch((error: unknown) => {
    privacyMigrationPromise = null;
    throw error;
  });
  try {
    await migration;
    return database;
  } catch (error) {
    database.close();
    throw error;
  }
}

export async function listDiscardTombstonesForOwner(ownerUserId: string) {
  const db = await openDb();
  try {
    const store = db.transaction(DISCARD_TOMBSTONE_STORE, "readonly")
      .objectStore(DISCARD_TOMBSTONE_STORE);
    return requestToPromise<AttendanceDiscardTombstone[]>(
      store.index(OWNER_INDEX).getAll(ownerUserId),
    );
  } finally {
    db.close();
  }
}

export async function updateDiscardTombstones(
  ownerUserId: string,
  rows: AttendanceDiscardTombstone[],
) {
  const db = await openDb();
  try {
    const transaction = db.transaction(DISCARD_TOMBSTONE_STORE, "readwrite");
    const completion = transactionToPromise(transaction);
    const store = transaction.objectStore(DISCARD_TOMBSTONE_STORE);
    for (const row of rows) {
      if (row.ownerUserId === ownerUserId) store.put(row);
    }
    await completion;
  } finally {
    db.close();
  }
}

export async function purgeExpiredSynchronizedDiscardTombstones(ownerUserId: string) {
  const cutoff = Date.now() - SYNCHRONIZED_DISCARD_RETENTION_MS;
  const db = await openDb();
  try {
    const transaction = db.transaction(DISCARD_TOMBSTONE_STORE, "readwrite");
    const completion = transactionToPromise(transaction);
    const store = transaction.objectStore(DISCARD_TOMBSTONE_STORE);
    const rows = await requestToPromise<AttendanceDiscardTombstone[]>(
      store.index(OWNER_INDEX).getAll(ownerUserId),
    );
    for (const row of rows) {
      const synchronizedAt = row.synchronizedAt
        ? Date.parse(row.synchronizedAt)
        : Number.NaN;
      if (
        row.syncState === "synchronized"
        && Number.isFinite(synchronizedAt)
        && synchronizedAt < cutoff
      ) {
        store.delete(row.id);
      }
    }
    await completion;
  } finally {
    db.close();
  }
}

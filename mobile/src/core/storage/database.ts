import * as Crypto from 'expo-crypto';
import { Directory, File } from 'expo-file-system';
import * as SQLite from 'expo-sqlite';

import { ACCOUNT_DATABASE_VERSION, migrateAccountDatabase } from './database-schema';

import { excludeAppPrivateUriFromBackup } from './ios-backup';
import {
  isManagedDatabaseArtifactName,
  isManagedDatabaseMainName,
} from './managed-database-artifacts';
import {
  clearDatabaseHealthMarker,
  getDatabaseHealthMarker,
  getOrCreateSecret,
  setDatabaseHealthMarker,
  type DatabaseHealthMarker,
} from './secure-store';

const DATABASE_VERSION = ACCOUNT_DATABASE_VERSION;
const DATABASE_HEALTH_MARKER_FORMAT_VERSION = 1;
const DATABASE_INTEGRITY_RECHECK_INTERVAL_MS = 7 * 24 * 60 * 60 * 1_000;
const DATABASE_HEALTH_CLOCK_TOLERANCE_MS = 5 * 60 * 1_000;

type ActiveDatabase = {
  database: SQLite.SQLiteDatabase;
  name: string;
  namespace: string;
  state: 'open' | 'closing';
  transactions: TransactionCoordinator;
  lastIntegrityCheckAtMs: number;
};

type TransactionCoordinator = {
  close: () => Promise<void>;
  run: (task: (transaction: SQLite.SQLiteDatabase) => Promise<void>) => Promise<void>;
  stop: () => void;
  wait: () => Promise<void>;
};

type PreparedDatabase = {
  database: SQLite.SQLiteDatabase;
  integrityCheckedAtMs: number | null;
  transactions: TransactionCoordinator;
};

export class OfflineDatabaseIntegrityError extends Error {
  readonly code = 'OFFLINE_DATABASE_INTEGRITY_FAILED';
  readonly localChangesPreserved = true;

  constructor() {
    super(
      'The offline database failed integrity verification. Local changes were preserved and the database was not replaced.',
    );
    this.name = 'OfflineDatabaseIntegrityError';
  }
}

let activeDatabase: ActiveDatabase | null = null;
let databaseLifecycleTail: Promise<void> = Promise.resolve();

function managedDatabaseDirectory(): Directory {
  const nativeDirectory: unknown = SQLite.defaultDatabaseDirectory;
  if (typeof nativeDirectory !== 'string') {
    throw new Error('The managed database directory is unavailable.');
  }
  const uri = nativeDirectory.startsWith('file:///')
    ? nativeDirectory
    : nativeDirectory.startsWith('/')
      ? `file://${nativeDirectory}`
      : null;
  if (!uri) throw new Error('The managed database directory is unavailable.');
  return new Directory(uri);
}

function listManagedDatabaseArtifacts(root: Directory): File[] {
  if (!root.exists) return [];
  const files = root.list().filter((entry): entry is File => entry instanceof File);
  const managed = files.filter((file) => isManagedDatabaseArtifactName(file.name));
  // Prevalidate the complete plan before any caller excludes or deletes files.
  // Directory.list() should already return direct children; reconstructing the
  // expected URI prevents a malformed native entry from escaping that root.
  for (const file of managed) {
    if (new File(root, file.name).uri !== file.uri) {
      throw new Error('A managed database artifact escaped its private directory.');
    }
  }
  return managed;
}

async function protectDatabaseArtifactsForName(name: string): Promise<void> {
  if (!isManagedDatabaseMainName(name)) throw new Error('Invalid managed database name.');
  const root = managedDatabaseDirectory();
  for (const file of listManagedDatabaseArtifacts(root)) {
    if (file.name === name || file.name.startsWith(`${name}-`)) {
      await excludeAppPrivateUriFromBackup(file.uri);
    }
  }
}

export async function protectManagedAccountDatabasesFromBackup(): Promise<void> {
  await runDatabaseLifecycle(async () => {
    if (activeDatabase) {
      throw new Error('Managed database backup protection must run before opening an account.');
    }
    const root = managedDatabaseDirectory();
    for (const file of listManagedDatabaseArtifacts(root)) {
      await excludeAppPrivateUriFromBackup(file.uri);
    }
  });
}

export async function deleteAllManagedAccountDatabases(): Promise<void> {
  await runDatabaseLifecycle(async () => {
    if (activeDatabase) {
      throw new Error('Managed database reset must run before opening an account.');
    }
    const root = managedDatabaseDirectory();
    const initial = listManagedDatabaseArtifacts(root);
    const mainNames = initial
      .filter((file) => isManagedDatabaseMainName(file.name))
      .map((file) => file.name);
    for (const name of mainNames) await SQLite.deleteDatabaseAsync(name);

    // deleteDatabaseAsync normally removes SQLite sidecars with the main file.
    // Remove only exact orphaned GC sidecars that remain; unrelated databases
    // and directories in Expo's shared SQLite directory are preserved.
    for (const file of listManagedDatabaseArtifacts(root)) {
      if (file.exists) file.delete();
    }
  });
}

function dirtyHealthMarker(previous: DatabaseHealthMarker | null): DatabaseHealthMarker {
  return {
    formatVersion: DATABASE_HEALTH_MARKER_FORMAT_VERSION,
    state: 'dirty',
    schemaVersion: previous?.schemaVersion ?? 0,
    lastIntegrityCheckAtMs: previous?.lastIntegrityCheckAtMs ?? 0,
  };
}

function shouldRunIntegrityCheck(
  marker: DatabaseHealthMarker | null,
  nowMs: number,
): boolean {
  if (!marker || marker.state !== 'clean' || marker.schemaVersion !== DATABASE_VERSION) {
    return true;
  }
  if (marker.lastIntegrityCheckAtMs <= 0) return true;
  if (marker.lastIntegrityCheckAtMs > nowMs + DATABASE_HEALTH_CLOCK_TOLERANCE_MS) return true;
  return nowMs - marker.lastIntegrityCheckAtMs >= DATABASE_INTEGRITY_RECHECK_INTERVAL_MS;
}

function runDatabaseLifecycle<T>(operation: () => Promise<T>): Promise<T> {
  const result = databaseLifecycleTail.then(operation, operation);
  databaseLifecycleTail = result.then(
    () => undefined,
    () => undefined,
  );
  return result;
}

async function configureDatabaseConnection(
  database: SQLite.SQLiteDatabase,
  key: string,
  includeJournalMode: boolean,
): Promise<void> {
  await database.execAsync(`PRAGMA key = "x'${key}'"`);
  const journalMode = includeJournalMode ? ' PRAGMA journal_mode = WAL;' : '';
  await database.execAsync(
    `PRAGMA foreign_keys = ON;${journalMode} PRAGMA busy_timeout = 5000;`,
  );
}

async function coordinateTransactions(
  name: string,
  key: string,
): Promise<TransactionCoordinator> {
  // Expo's withExclusiveTransactionAsync creates an internal connection but offers
  // no hook to apply SQLCipher's PRAGMA key before BEGIN. Use an explicitly opened,
  // keyed connection instead. Only transaction callbacks receive this connection,
  // so main-connection writes cannot become part of or roll back its transaction.
  const openTransactionConnection = async (): Promise<SQLite.SQLiteDatabase> => {
    const connection = await SQLite.openDatabaseAsync(name, { useNewConnection: true });
    try {
      await configureDatabaseConnection(connection, key, false);
      return connection;
    } catch (error) {
      await connection.closeAsync().catch(() => undefined);
      throw error;
    }
  };
  let transactionDatabase = await openTransactionConnection();

  let transactionTail: Promise<void> = Promise.resolve();
  let acceptingTransactions = true;
  let connectionClosed = false;
  let transactionConnectionFailed = false;

  const unavailableError = (): Error => new Error(
    'The offline database is closing and cannot start another transaction.',
  );

  const recoverTransactionConnection = async (): Promise<void> => {
    if (!transactionConnectionFailed) return;
    // Recovery runs inside the serialized transaction tail. No callback can
    // observe the replacement until the failed connection is closed, re-opened,
    // keyed, and configured. This avoids requiring an application restart after
    // a native rollback-state failure while retaining fail-closed ordering.
    await transactionDatabase.closeAsync();
    transactionDatabase = await openTransactionConnection();
    transactionConnectionFailed = false;
  };

  const run = (task: (transaction: SQLite.SQLiteDatabase) => Promise<void>): Promise<void> => {
    if (!acceptingTransactions) {
      return Promise.reject(unavailableError());
    }
    const result = transactionTail.then(async () => {
      if (!acceptingTransactions) throw unavailableError();
      await recoverTransactionConnection();
      if (!acceptingTransactions) throw unavailableError();
      let began = false;
      try {
        // IMMEDIATE acquires the write reservation before application work starts.
        // Other connections may read WAL snapshots, while writes wait or fail locked.
        await transactionDatabase.execAsync('BEGIN IMMEDIATE');
        began = true;
        await task(transactionDatabase);
        await transactionDatabase.execAsync('COMMIT');
      } catch (error) {
        if (began) {
          // Expo's non-exclusive helper can replace the application exception when
          // ROLLBACK also fails. Cleanup is best-effort; always preserve the original.
          try {
            await transactionDatabase.execAsync('ROLLBACK');
          } catch {
            // The connection's transaction state is now unknowable. Preserve the
            // task exception; the next serialized job replaces this connection.
            transactionConnectionFailed = true;
          }
        }
        throw error;
      }
    });
    transactionTail = result.then(
      () => undefined,
      () => undefined,
    );
    return result;
  };

  return {
    close: async () => {
      if (connectionClosed) return;
      await transactionDatabase.closeAsync();
      connectionClosed = true;
    },
    run,
    stop: () => {
      acceptingTransactions = false;
    },
    wait: () => transactionTail,
  };
}

async function databaseName(namespace: string): Promise<string> {
  const digest = await Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    namespace,
  );
  return `gc_${digest.slice(0, 32)}.db`;
}

async function passesQuickIntegrityCheck(database: SQLite.SQLiteDatabase): Promise<boolean> {
  try {
    // quick_check performs the same structural checks as integrity_check while
    // avoiding the UNIQUE-index verification cost. Limiting it to one result
    // also keeps cold-start work bounded when a database is damaged.
    const row = await database.getFirstAsync<Record<string, unknown>>('PRAGMA quick_check(1)');
    const status = row ? Object.values(row)[0] : null;
    return typeof status === 'string' && status.toLowerCase() === 'ok';
  } catch {
    // An unreadable SQLCipher database, invalid page, or native query failure is
    // never treated as healthy merely because no diagnostic text was returned.
    return false;
  }
}

async function hasVerifiedZeroPendingActions(
  database: SQLite.SQLiteDatabase,
): Promise<boolean> {
  try {
    const table = await database.getFirstAsync<{ table_exists: number }>(
      `SELECT 1 AS table_exists
         FROM sqlite_master
        WHERE type = 'table' AND name = 'pending_actions'
        LIMIT 1`,
    );
    if (!table) {
      // Only a brand-new, unmigrated database can safely lack the queue table.
      // A migrated database without it may have damaged schema pages, so fail closed.
      const version = await database.getFirstAsync<{ user_version: number }>(
        'PRAGMA user_version',
      );
      return version?.user_version === 0;
    }

    // Count every queue row, including rejected actions. Rejected mutations are
    // still part of the local audit trail and must not be silently discarded.
    const pending = await database.getFirstAsync<{ count: number }>(
      'SELECT COUNT(*) AS count FROM pending_actions',
    );
    return Number.isSafeInteger(pending?.count) && pending?.count === 0;
  } catch {
    // Corruption can make sqlite_master or the queue unreadable. An inability to
    // prove the queue is empty is intentionally equivalent to having local work.
    return false;
  }
}

async function closePreparedDatabase(
  database: SQLite.SQLiteDatabase,
  transactions: TransactionCoordinator | null,
  strict: boolean,
): Promise<boolean> {
  try {
    if (transactions) {
      transactions.stop();
      await transactions.wait();
      await transactions.close();
    }
    await database.closeAsync();
    return true;
  } catch (error) {
    if (strict) return false;
    throw error;
  }
}

async function prepareAccountDatabase(
  name: string,
  key: string,
  allowAutomaticRebuild: boolean,
  performInitialIntegrityCheck: boolean,
): Promise<PreparedDatabase> {
  const database = await SQLite.openDatabaseAsync(name);
  let transactions: TransactionCoordinator | null = null;
  let integrityCheckedAtMs: number | null = null;

  try {
    await configureDatabaseConnection(database, key, true);
  } catch (error) {
    await database.closeAsync().catch(() => undefined);
    throw error;
  }

  const recoverFromIntegrityFailure = async (): Promise<PreparedDatabase> => {
    const queueIsEmpty = await hasVerifiedZeroPendingActions(database);
    if (!queueIsEmpty || !allowAutomaticRebuild) {
      await closePreparedDatabase(database, transactions, true);
      throw new OfflineDatabaseIntegrityError();
    }

    // A database is deleted only after the queue was positively verified empty
    // and every native connection was closed. Any uncertainty leaves it in place.
    const closed = await closePreparedDatabase(database, transactions, true);
    if (!closed) throw new OfflineDatabaseIntegrityError();
    await SQLite.deleteDatabaseAsync(name);
    return prepareAccountDatabase(name, key, false, true);
  };

  if (performInitialIntegrityCheck) {
    if (!(await passesQuickIntegrityCheck(database))) {
      return recoverFromIntegrityFailure();
    }
    integrityCheckedAtMs = Date.now();
  }

  let didMigrate = false;
  try {
    transactions = await coordinateTransactions(name, key);
    didMigrate = await migrateAccountDatabase(database, transactions.run);
  } catch (error) {
    if (transactions) {
      transactions.stop();
      await transactions.wait();
      await transactions.close().catch(() => undefined);
    }
    await database.closeAsync().catch(() => undefined);
    throw error;
  }

  // A normal open performs one bounded check. Re-check only after schema writes,
  // avoiding a second full page walk on every cold start.
  if (didMigrate && !(await passesQuickIntegrityCheck(database))) {
    return recoverFromIntegrityFailure();
  }
  if (didMigrate) integrityCheckedAtMs = Date.now();

  return { database, integrityCheckedAtMs, transactions };
}

export async function openAccountDatabase(namespace: string): Promise<SQLite.SQLiteDatabase> {
  return runDatabaseLifecycle(async () => {
    // Enrol the open operation in the lifecycle queue before hashing the namespace.
    // Otherwise a close/delete invoked immediately after open can overtake this
    // operation while the asynchronous digest is still pending.
    const name = await databaseName(namespace);
    // A second caller commonly arrives while the first one is opening and migrating.
    // Re-check inside the lifecycle queue so both callers receive the same connection.
    if (activeDatabase?.name === name) {
      if (activeDatabase.state === 'open') return activeDatabase.database;
      throw new Error('The account database is closing and cannot be reopened yet.');
    }
    if (activeDatabase) {
      throw new Error('A different account database is already open. Close it before switching accounts.');
    }

    const previousHealth = await getDatabaseHealthMarker(namespace);
    const performInitialIntegrityCheck = shouldRunIntegrityCheck(previousHealth, Date.now());

    // Mark the database dirty before any native connection is opened. A process
    // crash, force-stop, or failed close therefore forces validation next time.
    await setDatabaseHealthMarker(namespace, dirtyHealthMarker(previousHealth));

    const key = await getOrCreateSecret(namespace, 'database-key');
    if (!/^[0-9a-f]{64}$/i.test(key)) throw new Error('Invalid database encryption key.');

    const prepared = await prepareAccountDatabase(
      name,
      key,
      true,
      performInitialIntegrityCheck,
    );
    const lastIntegrityCheckAtMs = prepared.integrityCheckedAtMs
      ?? previousHealth?.lastIntegrityCheckAtMs
      ?? 0;

    try {
      await protectDatabaseArtifactsForName(name);
      // Keep the state dirty throughout the open session while persisting any
      // newly completed integrity-check timestamp for a later clean close.
      await setDatabaseHealthMarker(namespace, {
        formatVersion: DATABASE_HEALTH_MARKER_FORMAT_VERSION,
        state: 'dirty',
        schemaVersion: DATABASE_VERSION,
        lastIntegrityCheckAtMs,
      });
    } catch (error) {
      await closePreparedDatabase(prepared.database, prepared.transactions, true);
      throw error;
    }

    activeDatabase = {
      database: prepared.database,
      name,
      namespace,
      state: 'open',
      transactions: prepared.transactions,
      lastIntegrityCheckAtMs,
    };
    return prepared.database;
  });
}

export function withAccountTransaction(
  database: SQLite.SQLiteDatabase,
  task: (transaction: SQLite.SQLiteDatabase) => Promise<void>,
): Promise<void> {
  const active = activeDatabase;
  if (!active || active.database !== database) {
    return Promise.reject(new Error('The account database is not the active offline database.'));
  }
  if (active.state !== 'open') {
    return Promise.reject(new Error('The offline database is closing and cannot start another transaction.'));
  }
  return active.transactions.run(task);
}

export async function closeAccountDatabase(): Promise<void> {
  await runDatabaseLifecycle(async () => {
    const active = activeDatabase;
    if (!active) return;
    active.state = 'closing';
    active.transactions.stop();
    await active.transactions.wait();
    await active.transactions.close();
    await active.database.closeAsync();
    // Retain ownership until the native connection confirms it is closed. If
    // closeAsync fails, later opens remain fail-closed and close can be retried.
    if (activeDatabase === active) activeDatabase = null;
    await setDatabaseHealthMarker(active.namespace, {
      formatVersion: DATABASE_HEALTH_MARKER_FORMAT_VERSION,
      state: 'clean',
      schemaVersion: DATABASE_VERSION,
      lastIntegrityCheckAtMs: active.lastIntegrityCheckAtMs,
    });
  });
}

export async function deleteAccountDatabase(namespace: string): Promise<void> {
  await runDatabaseLifecycle(async () => {
    // Preserve call order with an in-flight open even while deriving the filename.
    const name = await databaseName(namespace);
    if (activeDatabase?.name === name) {
      const active = activeDatabase;
      active.state = 'closing';
      active.transactions.stop();
      await active.transactions.wait();
      await active.transactions.close();
      await active.database.closeAsync();
      if (activeDatabase === active) activeDatabase = null;
    }
    await clearDatabaseHealthMarker(namespace);
    await SQLite.deleteDatabaseAsync(name);
  });
}

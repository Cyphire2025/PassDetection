import * as Crypto from 'expo-crypto';
import { Directory, File } from 'expo-file-system';
import * as SQLite from 'expo-sqlite';

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

const DATABASE_VERSION = 16;
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
    didMigrate = await migrate(database, transactions.run);
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

async function migrate(
  database: SQLite.SQLiteDatabase,
  runTransaction: TransactionCoordinator['run'],
): Promise<boolean> {
  const result = await database.getFirstAsync<{ user_version: number }>('PRAGMA user_version');
  const currentVersion = result?.user_version ?? 0;

  if (currentVersion > DATABASE_VERSION) {
    throw new Error('The offline database was created by a newer application version.');
  }

  if (currentVersion === 0) {
    await runTransaction(async (transaction) => {
      await transaction.execAsync(`
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY NOT NULL,
          account_id TEXT NOT NULL,
          account_namespace TEXT NOT NULL,
          agency_id TEXT NOT NULL,
          principal_type TEXT NOT NULL CHECK (principal_type IN ('passenger', 'client_manager', 'coordinator')),
          passenger_id TEXT,
          display_name TEXT NOT NULL,
          email TEXT,
          phone_number TEXT,
          updated_at TEXT NOT NULL,
          session_id TEXT NOT NULL,
          access_token_expires_at TEXT NOT NULL,
          refresh_token_expires_at TEXT NOT NULL,
          force_password_change INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_users_account
          ON users(account_namespace, account_id);

        CREATE TABLE IF NOT EXISTS trips (
          id TEXT PRIMARY KEY NOT NULL,
          account_namespace TEXT NOT NULL,
          agency_id TEXT NOT NULL,
          role TEXT NOT NULL,
          name TEXT NOT NULL,
          destination TEXT,
          travel_date TEXT,
          return_date TEXT,
          access_generation INTEGER NOT NULL,
          access_expires_at TEXT,
          itinerary_version INTEGER NOT NULL DEFAULT -1,
          common_document_version INTEGER NOT NULL DEFAULT -1,
          personal_document_version INTEGER NOT NULL DEFAULT -1,
          announcement_version INTEGER NOT NULL DEFAULT -1,
          readiness_version INTEGER NOT NULL DEFAULT -1,
          roster_version INTEGER NOT NULL DEFAULT -1,
          rooming_version INTEGER NOT NULL DEFAULT -1,
          meals_version INTEGER NOT NULL DEFAULT -1,
          qr_version INTEGER NOT NULL DEFAULT -1,
          advertised_itinerary_version INTEGER NOT NULL DEFAULT 0,
          advertised_common_document_version INTEGER NOT NULL DEFAULT 0,
          advertised_personal_document_version INTEGER NOT NULL DEFAULT 0,
          advertised_announcement_version INTEGER NOT NULL DEFAULT 0,
          advertised_readiness_version INTEGER NOT NULL DEFAULT 0,
          advertised_roster_version INTEGER NOT NULL DEFAULT 0,
          advertised_rooming_version INTEGER NOT NULL DEFAULT 0,
          advertised_meals_version INTEGER NOT NULL DEFAULT 0,
          advertised_qr_version INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_trips_namespace ON trips(account_namespace, travel_date);

        CREATE TABLE IF NOT EXISTS trip_purge_tombstones (
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL,
          purge_epoch INTEGER NOT NULL DEFAULT 1,
          blocked_access_generation INTEGER,
          reason TEXT NOT NULL CHECK (reason IN (
            'access_revoked', 'access_expired', 'server_removed',
            'generation_changed', 'authorization_denied'
          )),
          attempt_count INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          last_attempt_at TEXT,
          last_error_code TEXT,
          PRIMARY KEY(account_namespace, trip_id)
        );
        CREATE INDEX IF NOT EXISTS idx_trip_purge_retry
          ON trip_purge_tombstones(account_namespace, last_attempt_at, created_at);
        CREATE TRIGGER IF NOT EXISTS block_trip_insert_pending_purge
          BEFORE INSERT ON trips
          WHEN EXISTS (
            SELECT 1 FROM trip_purge_tombstones purge
             WHERE purge.account_namespace = NEW.account_namespace
               AND purge.trip_id = NEW.id
          )
        BEGIN
          SELECT RAISE(ABORT, 'trip purge pending');
        END;

        CREATE TABLE IF NOT EXISTS itinerary_days (
          id TEXT PRIMARY KEY NOT NULL,
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          version INTEGER NOT NULL,
          day_number INTEGER NOT NULL,
          calendar_date TEXT,
          title TEXT,
          sort_order INTEGER NOT NULL,
          UNIQUE(account_namespace, trip_id, version, day_number)
        );

        CREATE TABLE IF NOT EXISTS itinerary_items (
          id TEXT PRIMARY KEY NOT NULL,
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          day_id TEXT NOT NULL REFERENCES itinerary_days(id) ON DELETE CASCADE,
          version INTEGER NOT NULL,
          title TEXT NOT NULL,
          description TEXT,
          starts_at TEXT,
          ends_at TEXT,
          location_name TEXT,
          latitude REAL,
          longitude REAL,
          sort_order INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_itinerary_trip ON itinerary_items(account_namespace, trip_id, version, sort_order);

        CREATE TABLE IF NOT EXISTS announcements (
          id TEXT PRIMARY KEY NOT NULL,
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          version INTEGER NOT NULL,
          title TEXT NOT NULL,
          message TEXT NOT NULL,
          priority TEXT NOT NULL,
          published_at TEXT NOT NULL,
          available_until TEXT,
          is_read INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_announcements_trip ON announcements(account_namespace, trip_id, published_at DESC);

        CREATE TABLE IF NOT EXISTS document_metadata (
          id TEXT PRIMARY KEY NOT NULL,
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          passenger_id TEXT,
          scope TEXT NOT NULL CHECK (scope IN ('personal', 'common', 'coordinator')),
          category TEXT NOT NULL,
          display_name TEXT NOT NULL,
          content_type TEXT NOT NULL,
          size_bytes INTEGER NOT NULL,
          version INTEGER NOT NULL,
          checksum_sha256 TEXT NOT NULL,
          offline_available INTEGER NOT NULL DEFAULT 1,
          metadata_state TEXT NOT NULL DEFAULT 'ready' CHECK (metadata_state IN ('ready', 'pending')),
          updated_at TEXT NOT NULL,
          revoked_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_documents_owner ON document_metadata(account_namespace, trip_id, passenger_id, scope);
        CREATE INDEX IF NOT EXISTS idx_documents_active_listing
          ON document_metadata(account_namespace, trip_id, scope DESC, category, display_name)
          WHERE revoked_at IS NULL;

        CREATE TABLE IF NOT EXISTS offline_files (
          document_id TEXT PRIMARY KEY NOT NULL REFERENCES document_metadata(id) ON DELETE CASCADE,
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL,
          version INTEGER NOT NULL,
          encrypted_path TEXT NOT NULL,
          checksum_sha256 TEXT NOT NULL,
          encrypted_size_bytes INTEGER NOT NULL,
          downloaded_at TEXT NOT NULL,
          last_opened_at TEXT
        );

        CREATE TABLE IF NOT EXISTS offline_document_jobs (
          document_id TEXT PRIMARY KEY NOT NULL REFERENCES document_metadata(id) ON DELETE CASCADE,
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          version INTEGER NOT NULL,
          state TEXT NOT NULL CHECK (state IN ('pending', 'retryable', 'blocked')),
          attempt_count INTEGER NOT NULL DEFAULT 0,
          next_attempt_at TEXT,
          last_error_code TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_offline_document_jobs_due
          ON offline_document_jobs(account_namespace, trip_id, state, next_attempt_at, updated_at);

        CREATE TABLE IF NOT EXISTS passenger_profiles (
          passenger_id TEXT PRIMARY KEY NOT NULL,
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          display_name TEXT NOT NULL,
          personal_status TEXT,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS room_assignments (
          id TEXT PRIMARY KEY NOT NULL,
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          passenger_id TEXT,
          hotel_name TEXT,
          room_number TEXT,
          roommate_summary TEXT,
          version INTEGER NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS meal_information (
          id TEXT PRIMARY KEY NOT NULL,
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          passenger_id TEXT,
          preference TEXT,
          notes TEXT,
          version INTEGER NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS qr_metadata (
          id TEXT PRIMARY KEY NOT NULL,
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          passenger_id TEXT,
          signed_payload TEXT NOT NULL,
          version INTEGER NOT NULL,
          valid_from TEXT,
          valid_until TEXT,
          offline_allowed INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS coordinator_passengers (
          id TEXT NOT NULL,
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          display_name TEXT NOT NULL,
          employee_code TEXT,
          employee_type TEXT,
          attendance_status TEXT NOT NULL,
          phone_number TEXT,
          email TEXT,
          departure_city TEXT,
          nearest_domestic_airport TEXT,
          designation TEXT,
          department TEXT,
          gender TEXT,
          date_of_birth TEXT,
          nationality TEXT,
          hotel_name TEXT,
          room_number TEXT,
          roommate_summary TEXT,
          meal_preference TEXT,
          family_relation TEXT,
          family_head_name TEXT,
          family_head_phone TEXT,
          family_head_email TEXT,
          passport_status TEXT CHECK (passport_status IS NULL OR passport_status IN ('available', 'not_available')),
          visa_status TEXT CHECK (visa_status IS NULL OR visa_status IN ('available', 'not_available')),
          flight_ticket_status TEXT CHECK (flight_ticket_status IS NULL OR flight_ticket_status IN ('available', 'not_available')),
          has_alert INTEGER NOT NULL DEFAULT 0,
          detail_updated_at TEXT,
          detail_payload_json TEXT,
          detail_contract_version INTEGER,
          roster_version INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(account_namespace, trip_id, id)
        );
        CREATE INDEX IF NOT EXISTS idx_coordinator_roster_search
          ON coordinator_passengers(account_namespace, trip_id, display_name, employee_code);

        CREATE TABLE IF NOT EXISTS sync_cursors (
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL,
          cursor INTEGER NOT NULL DEFAULT 0,
          access_generation INTEGER NOT NULL,
          last_synced_at TEXT,
          last_error_code TEXT,
          PRIMARY KEY(account_namespace, trip_id)
        );

        CREATE TABLE IF NOT EXISTS pending_actions (
          idempotency_key TEXT PRIMARY KEY NOT NULL,
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          action_type TEXT NOT NULL,
          dedupe_key TEXT,
          payload_json TEXT NOT NULL,
          base_version INTEGER,
          state TEXT NOT NULL CHECK (state IN ('pending', 'sending', 'retryable', 'rejected')),
          attempt_count INTEGER NOT NULL DEFAULT 0,
          next_attempt_at TEXT,
          last_error_code TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pending_drain ON pending_actions(account_namespace, trip_id, state, next_attempt_at, created_at);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_action_dedupe
          ON pending_actions(account_namespace, trip_id, action_type, dedupe_key)
          WHERE dedupe_key IS NOT NULL;

        CREATE TABLE IF NOT EXISTS attendance_scan_receipts (
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          session_id TEXT NOT NULL,
          dedupe_key TEXT NOT NULL,
          client_event_id TEXT NOT NULL,
          server_status TEXT NOT NULL CHECK (server_status IN ('accepted', 'already_applied')),
          accepted_at TEXT NOT NULL,
          PRIMARY KEY(account_namespace, trip_id, session_id, dedupe_key)
        );
        CREATE INDEX IF NOT EXISTS idx_attendance_scan_receipts_session
          ON attendance_scan_receipts(account_namespace, trip_id, session_id, accepted_at);

        CREATE TABLE IF NOT EXISTS manager_readiness (
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          passenger_count INTEGER NOT NULL,
          passports_complete INTEGER NOT NULL,
          visas_available INTEGER NOT NULL,
          tickets_available INTEGER NOT NULL,
          items_needing_attention INTEGER NOT NULL,
          rooms_assigned INTEGER NOT NULL,
          meals_confirmed INTEGER NOT NULL,
          version INTEGER NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(account_namespace, trip_id)
        );

        CREATE TABLE IF NOT EXISTS attendance_summaries (
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          total INTEGER NOT NULL,
          present INTEGER NOT NULL,
          missing INTEGER NOT NULL,
          excused INTEGER NOT NULL,
          not_marked INTEGER NOT NULL,
          version INTEGER NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(account_namespace, trip_id)
        );

        CREATE TABLE IF NOT EXISTS attendance_sessions (
          id TEXT PRIMARY KEY NOT NULL,
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          name TEXT NOT NULL,
          status TEXT NOT NULL CHECK (status IN ('draft', 'active', 'completed', 'cancelled')),
          scanned_count INTEGER NOT NULL,
          assigned_count INTEGER NOT NULL,
          started_at TEXT,
          completed_at TEXT,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_attendance_sessions_trip
          ON attendance_sessions(account_namespace, trip_id, status, started_at DESC);

        CREATE TABLE IF NOT EXISTS attendance_session_selection (
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          session_id TEXT NOT NULL,
          selected_at TEXT NOT NULL,
          PRIMARY KEY(account_namespace, trip_id)
        );

        CREATE TABLE IF NOT EXISTS attendance_session_missing (
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          session_id TEXT NOT NULL,
          passenger_id TEXT NOT NULL,
          display_name TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(account_namespace, trip_id, session_id, passenger_id)
        );

        CREATE TABLE IF NOT EXISTS operation_snapshots (
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          resource_type TEXT NOT NULL CHECK (resource_type IN ('rooming', 'meals', 'tasks', 'incidents')),
          version INTEGER NOT NULL,
          payload_json TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(account_namespace, trip_id, resource_type)
        );

        CREATE TABLE IF NOT EXISTS mobile_notifications (
          id TEXT PRIMARY KEY NOT NULL,
          account_namespace TEXT NOT NULL,
          trip_id TEXT,
          notification_type TEXT NOT NULL,
          category TEXT NOT NULL,
          priority TEXT NOT NULL CHECK (priority IN ('normal', 'important', 'emergency')),
          title TEXT NOT NULL,
          body TEXT NOT NULL,
          deep_link_path TEXT,
          available_at TEXT NOT NULL,
          expires_at TEXT,
          read_at TEXT,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_mobile_notifications_feed
          ON mobile_notifications(account_namespace, trip_id, available_at DESC);
      `);
      await transaction.execAsync(`PRAGMA user_version = ${DATABASE_VERSION}`);
    });
    return true;
  }

  if (currentVersion < 2) {
    await runTransaction(async (transaction) => {
      await transaction.execAsync(`
        ALTER TABLE pending_actions ADD COLUMN dedupe_key TEXT;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_action_dedupe
          ON pending_actions(account_namespace, trip_id, action_type, dedupe_key)
          WHERE dedupe_key IS NOT NULL;

        CREATE TABLE IF NOT EXISTS manager_readiness (
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          passenger_count INTEGER NOT NULL,
          passports_complete INTEGER NOT NULL,
          visas_available INTEGER NOT NULL,
          tickets_available INTEGER NOT NULL,
          items_needing_attention INTEGER NOT NULL,
          rooms_assigned INTEGER NOT NULL,
          meals_confirmed INTEGER NOT NULL,
          version INTEGER NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(account_namespace, trip_id)
        );

        CREATE TABLE IF NOT EXISTS attendance_summaries (
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          total INTEGER NOT NULL,
          present INTEGER NOT NULL,
          missing INTEGER NOT NULL,
          excused INTEGER NOT NULL,
          not_marked INTEGER NOT NULL,
          version INTEGER NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(account_namespace, trip_id)
        );

        CREATE TABLE IF NOT EXISTS operation_snapshots (
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          resource_type TEXT NOT NULL CHECK (resource_type IN ('rooming', 'meals', 'tasks', 'incidents')),
          version INTEGER NOT NULL,
          payload_json TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(account_namespace, trip_id, resource_type)
        );
      `);
      await transaction.execAsync('PRAGMA user_version = 2');
    });
  }

  if (currentVersion < 3) {
    await runTransaction(async (transaction) => {
      await transaction.execAsync('ALTER TABLE trips ADD COLUMN access_expires_at TEXT');
      await transaction.execAsync('PRAGMA user_version = 3');
    });
  }

  if (currentVersion < 4) {
    await runTransaction(async (transaction) => {
      await transaction.execAsync(`
        ALTER TABLE users ADD COLUMN session_id TEXT;
        ALTER TABLE users ADD COLUMN access_token_expires_at TEXT;
        ALTER TABLE users ADD COLUMN refresh_token_expires_at TEXT;
        ALTER TABLE users ADD COLUMN force_password_change INTEGER NOT NULL DEFAULT 0;
      `);
      await transaction.execAsync('DELETE FROM users WHERE session_id IS NULL OR refresh_token_expires_at IS NULL');
      await transaction.execAsync('PRAGMA user_version = 4');
    });
  }

  if (currentVersion < 5) {
    await runTransaction(async (transaction) => {
      await transaction.execAsync(`
        CREATE TABLE IF NOT EXISTS mobile_notifications (
          id TEXT PRIMARY KEY NOT NULL,
          account_namespace TEXT NOT NULL,
          trip_id TEXT,
          notification_type TEXT NOT NULL,
          category TEXT NOT NULL,
          priority TEXT NOT NULL CHECK (priority IN ('normal', 'important', 'emergency')),
          title TEXT NOT NULL,
          body TEXT NOT NULL,
          deep_link_path TEXT,
          available_at TEXT NOT NULL,
          expires_at TEXT,
          read_at TEXT,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_mobile_notifications_feed
          ON mobile_notifications(account_namespace, trip_id, available_at DESC);
        PRAGMA user_version = 5;
      `);
    });
  }

  if (currentVersion < 6) {
    await runTransaction(async (transaction) => {
      await transaction.execAsync(`
        ALTER TABLE document_metadata ADD COLUMN offline_available INTEGER NOT NULL DEFAULT 1;
        ALTER TABLE document_metadata ADD COLUMN metadata_state TEXT NOT NULL DEFAULT 'ready'
          CHECK (metadata_state IN ('ready', 'pending'));
        PRAGMA user_version = 6;
      `);
    });
  }

  if (currentVersion < 7) {
    await runTransaction(async (transaction) => {
      await transaction.execAsync(`
        CREATE TABLE IF NOT EXISTS attendance_sessions (
          id TEXT PRIMARY KEY NOT NULL,
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          name TEXT NOT NULL,
          status TEXT NOT NULL CHECK (status IN ('draft', 'active', 'completed', 'cancelled')),
          scanned_count INTEGER NOT NULL,
          assigned_count INTEGER NOT NULL,
          started_at TEXT,
          completed_at TEXT,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_attendance_sessions_trip
          ON attendance_sessions(account_namespace, trip_id, status, started_at DESC);
        CREATE TABLE IF NOT EXISTS attendance_session_selection (
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          session_id TEXT NOT NULL,
          selected_at TEXT NOT NULL,
          PRIMARY KEY(account_namespace, trip_id)
        );
        CREATE TABLE IF NOT EXISTS attendance_session_missing (
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          session_id TEXT NOT NULL,
          passenger_id TEXT NOT NULL,
          display_name TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(account_namespace, trip_id, session_id, passenger_id)
        );
        PRAGMA user_version = 7;
      `);
    });
  }

  if (currentVersion < 8) {
    await runTransaction(async (transaction) => {
      await transaction.execAsync(`
        ALTER TABLE trips ADD COLUMN personal_document_version INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE trips ADD COLUMN readiness_version INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE trips ADD COLUMN roster_version INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE trips ADD COLUMN rooming_version INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE trips ADD COLUMN meals_version INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE trips ADD COLUMN qr_version INTEGER NOT NULL DEFAULT 0;
        PRAGMA user_version = 8;
      `);
    });
  }

  if (currentVersion < 9) {
    await runTransaction(async (transaction) => {
      await transaction.execAsync(`
        ALTER TABLE users ADD COLUMN email TEXT;
        ALTER TABLE users ADD COLUMN phone_number TEXT;
        PRAGMA user_version = 9;
      `);
    });
  }

  if (currentVersion < 10) {
    await runTransaction(async (transaction) => {
      await transaction.execAsync(`
        CREATE TABLE IF NOT EXISTS attendance_scan_receipts (
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          session_id TEXT NOT NULL,
          dedupe_key TEXT NOT NULL,
          client_event_id TEXT NOT NULL,
          server_status TEXT NOT NULL CHECK (server_status IN ('accepted', 'already_applied')),
          accepted_at TEXT NOT NULL,
          PRIMARY KEY(account_namespace, trip_id, session_id, dedupe_key)
        );
        CREATE INDEX IF NOT EXISTS idx_attendance_scan_receipts_session
          ON attendance_scan_receipts(account_namespace, trip_id, session_id, accepted_at);
        PRAGMA user_version = 10;
      `);
    });
  }

  if (currentVersion < 11) {
    await runTransaction(async (transaction) => {
      await transaction.execAsync(`
        ALTER TABLE coordinator_passengers ADD COLUMN employee_type TEXT;
        ALTER TABLE coordinator_passengers ADD COLUMN phone_number TEXT;
        ALTER TABLE coordinator_passengers ADD COLUMN email TEXT;
        ALTER TABLE coordinator_passengers ADD COLUMN departure_city TEXT;
        ALTER TABLE coordinator_passengers ADD COLUMN nearest_domestic_airport TEXT;
        ALTER TABLE coordinator_passengers ADD COLUMN designation TEXT;
        ALTER TABLE coordinator_passengers ADD COLUMN department TEXT;
        ALTER TABLE coordinator_passengers ADD COLUMN gender TEXT;
        ALTER TABLE coordinator_passengers ADD COLUMN date_of_birth TEXT;
        ALTER TABLE coordinator_passengers ADD COLUMN nationality TEXT;
        ALTER TABLE coordinator_passengers ADD COLUMN hotel_name TEXT;
        ALTER TABLE coordinator_passengers ADD COLUMN roommate_summary TEXT;
        ALTER TABLE coordinator_passengers ADD COLUMN family_relation TEXT;
        ALTER TABLE coordinator_passengers ADD COLUMN family_head_name TEXT;
        ALTER TABLE coordinator_passengers ADD COLUMN family_head_phone TEXT;
        ALTER TABLE coordinator_passengers ADD COLUMN family_head_email TEXT;
        ALTER TABLE coordinator_passengers ADD COLUMN passport_status TEXT
          CHECK (passport_status IS NULL OR passport_status IN ('available', 'not_available'));
        ALTER TABLE coordinator_passengers ADD COLUMN visa_status TEXT
          CHECK (visa_status IS NULL OR visa_status IN ('available', 'not_available'));
        ALTER TABLE coordinator_passengers ADD COLUMN flight_ticket_status TEXT
          CHECK (flight_ticket_status IS NULL OR flight_ticket_status IN ('available', 'not_available'));
        ALTER TABLE coordinator_passengers ADD COLUMN detail_updated_at TEXT;
        PRAGMA user_version = 11;
      `);
    });
  }

  if (currentVersion < 12) {
    await runTransaction(async (transaction) => {
      await transaction.execAsync(`
        ALTER TABLE coordinator_passengers ADD COLUMN detail_payload_json TEXT;
        ALTER TABLE coordinator_passengers ADD COLUMN detail_contract_version INTEGER;
        PRAGMA user_version = 12;
      `);
    });
  }

  if (currentVersion < 13) {
    await runTransaction(async (transaction) => {
      await transaction.execAsync(`
        ALTER TABLE users ADD COLUMN account_id TEXT;
        UPDATE users SET account_id = id WHERE account_id IS NULL OR account_id = '';
        CREATE INDEX IF NOT EXISTS idx_users_account
          ON users(account_namespace, account_id);

        ALTER TABLE trips ADD COLUMN advertised_itinerary_version INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE trips ADD COLUMN advertised_common_document_version INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE trips ADD COLUMN advertised_personal_document_version INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE trips ADD COLUMN advertised_announcement_version INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE trips ADD COLUMN advertised_readiness_version INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE trips ADD COLUMN advertised_roster_version INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE trips ADD COLUMN advertised_rooming_version INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE trips ADD COLUMN advertised_meals_version INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE trips ADD COLUMN advertised_qr_version INTEGER NOT NULL DEFAULT 0;

        UPDATE trips SET
          advertised_itinerary_version = itinerary_version,
          advertised_common_document_version = common_document_version,
          advertised_personal_document_version = personal_document_version,
          advertised_announcement_version = announcement_version,
          advertised_readiness_version = readiness_version,
          advertised_roster_version = roster_version,
          advertised_rooming_version = rooming_version,
          advertised_meals_version = meals_version,
          advertised_qr_version = qr_version,
          itinerary_version = -1,
          common_document_version = -1,
          personal_document_version = -1,
          announcement_version = -1,
          readiness_version = -1,
          roster_version = -1,
          rooming_version = -1,
          meals_version = -1,
          qr_version = -1;

        DELETE FROM sync_cursors;
        CREATE INDEX IF NOT EXISTS idx_documents_active_listing
          ON document_metadata(account_namespace, trip_id, scope DESC, category, display_name)
          WHERE revoked_at IS NULL;
        PRAGMA user_version = 13;
      `);
    });
  }

  if (currentVersion < 14) {
    await runTransaction(async (transaction) => {
      await transaction.execAsync(`
        CREATE TABLE IF NOT EXISTS trip_purge_tombstones (
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL,
          purge_epoch INTEGER NOT NULL DEFAULT 1,
          blocked_access_generation INTEGER,
          reason TEXT NOT NULL CHECK (reason IN (
            'access_revoked', 'access_expired', 'server_removed',
            'generation_changed', 'authorization_denied'
          )),
          attempt_count INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          last_attempt_at TEXT,
          last_error_code TEXT,
          PRIMARY KEY(account_namespace, trip_id)
        );
        CREATE INDEX IF NOT EXISTS idx_trip_purge_retry
          ON trip_purge_tombstones(account_namespace, last_attempt_at, created_at);
        CREATE TRIGGER IF NOT EXISTS block_trip_insert_pending_purge
          BEFORE INSERT ON trips
          WHEN EXISTS (
            SELECT 1 FROM trip_purge_tombstones purge
             WHERE purge.account_namespace = NEW.account_namespace
               AND purge.trip_id = NEW.id
          )
        BEGIN
          SELECT RAISE(ABORT, 'trip purge pending');
        END;
        PRAGMA user_version = 14;
      `);
    });
  }

  if (currentVersion < 15) {
    await runTransaction(async (transaction) => {
      await transaction.execAsync(`
        CREATE TABLE IF NOT EXISTS offline_document_jobs (
          document_id TEXT PRIMARY KEY NOT NULL REFERENCES document_metadata(id) ON DELETE CASCADE,
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          version INTEGER NOT NULL,
          state TEXT NOT NULL CHECK (state IN ('pending', 'retryable', 'blocked')),
          attempt_count INTEGER NOT NULL DEFAULT 0,
          next_attempt_at TEXT,
          last_error_code TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_offline_document_jobs_due
          ON offline_document_jobs(account_namespace, trip_id, state, next_attempt_at, updated_at);
        PRAGMA user_version = 15;
      `);
    });
  }

  if (currentVersion < 16) {
    await runTransaction(async (transaction) => {
      await transaction.execAsync(`
        ALTER TABLE users ADD COLUMN passenger_id TEXT;
        PRAGMA user_version = 16;
      `);
    });
  }

  return currentVersion < DATABASE_VERSION;
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

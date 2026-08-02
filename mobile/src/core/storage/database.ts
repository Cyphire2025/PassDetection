import * as Crypto from 'expo-crypto';
import * as SQLite from 'expo-sqlite';

import { getOrCreateSecret } from './secure-store';

const DATABASE_VERSION = 10;

let activeDatabase: SQLite.SQLiteDatabase | null = null;
let activeDatabaseName: string | null = null;

async function databaseName(namespace: string): Promise<string> {
  const digest = await Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    namespace,
  );
  return `gc_${digest.slice(0, 32)}.db`;
}

async function migrate(database: SQLite.SQLiteDatabase): Promise<void> {
  const result = await database.getFirstAsync<{ user_version: number }>('PRAGMA user_version');
  const currentVersion = result?.user_version ?? 0;

  if (currentVersion > DATABASE_VERSION) {
    throw new Error('The offline database was created by a newer application version.');
  }

  if (currentVersion === 0) {
    await database.withTransactionAsync(async () => {
      await database.execAsync(`
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY NOT NULL,
          account_namespace TEXT NOT NULL,
          agency_id TEXT NOT NULL,
          principal_type TEXT NOT NULL CHECK (principal_type IN ('passenger', 'client_manager', 'coordinator')),
          display_name TEXT NOT NULL,
          email TEXT,
          phone_number TEXT,
          updated_at TEXT NOT NULL,
          session_id TEXT NOT NULL,
          access_token_expires_at TEXT NOT NULL,
          refresh_token_expires_at TEXT NOT NULL,
          force_password_change INTEGER NOT NULL DEFAULT 0
        );

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
          itinerary_version INTEGER NOT NULL DEFAULT 0,
          common_document_version INTEGER NOT NULL DEFAULT 0,
          personal_document_version INTEGER NOT NULL DEFAULT 0,
          announcement_version INTEGER NOT NULL DEFAULT 0,
          readiness_version INTEGER NOT NULL DEFAULT 0,
          roster_version INTEGER NOT NULL DEFAULT 0,
          rooming_version INTEGER NOT NULL DEFAULT 0,
          meals_version INTEGER NOT NULL DEFAULT 0,
          qr_version INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_trips_namespace ON trips(account_namespace, travel_date);

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
          attendance_status TEXT NOT NULL,
          room_number TEXT,
          meal_preference TEXT,
          has_alert INTEGER NOT NULL DEFAULT 0,
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
      await database.execAsync(`PRAGMA user_version = ${DATABASE_VERSION}`);
    });
    return;
  }

  if (currentVersion < 2) {
    await database.withTransactionAsync(async () => {
      await database.execAsync(`
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
      await database.execAsync('PRAGMA user_version = 2');
    });
  }

  if (currentVersion < 3) {
    await database.withTransactionAsync(async () => {
      await database.execAsync('ALTER TABLE trips ADD COLUMN access_expires_at TEXT');
      await database.execAsync('PRAGMA user_version = 3');
    });
  }

  if (currentVersion < 4) {
    await database.withTransactionAsync(async () => {
      await database.execAsync(`
        ALTER TABLE users ADD COLUMN session_id TEXT;
        ALTER TABLE users ADD COLUMN access_token_expires_at TEXT;
        ALTER TABLE users ADD COLUMN refresh_token_expires_at TEXT;
        ALTER TABLE users ADD COLUMN force_password_change INTEGER NOT NULL DEFAULT 0;
      `);
      await database.execAsync('DELETE FROM users WHERE session_id IS NULL OR refresh_token_expires_at IS NULL');
      await database.execAsync('PRAGMA user_version = 4');
    });
  }

  if (currentVersion < 5) {
    await database.withTransactionAsync(async () => {
      await database.execAsync(`
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
    await database.withTransactionAsync(async () => {
      await database.execAsync(`
        ALTER TABLE document_metadata ADD COLUMN offline_available INTEGER NOT NULL DEFAULT 1;
        ALTER TABLE document_metadata ADD COLUMN metadata_state TEXT NOT NULL DEFAULT 'ready'
          CHECK (metadata_state IN ('ready', 'pending'));
        PRAGMA user_version = 6;
      `);
    });
  }

  if (currentVersion < 7) {
    await database.withTransactionAsync(async () => {
      await database.execAsync(`
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
    await database.withTransactionAsync(async () => {
      await database.execAsync(`
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
    await database.withTransactionAsync(async () => {
      await database.execAsync(`
        ALTER TABLE users ADD COLUMN email TEXT;
        ALTER TABLE users ADD COLUMN phone_number TEXT;
        PRAGMA user_version = 9;
      `);
    });
  }

  if (currentVersion < 10) {
    await database.withTransactionAsync(async () => {
      await database.execAsync(`
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
}

export async function openAccountDatabase(namespace: string): Promise<SQLite.SQLiteDatabase> {
  const name = await databaseName(namespace);
  if (activeDatabase && activeDatabaseName === name) return activeDatabase;
  await closeAccountDatabase();

  const key = await getOrCreateSecret(namespace, 'database-key');
  if (!/^[0-9a-f]{64}$/i.test(key)) throw new Error('Invalid database encryption key.');

  const database = await SQLite.openDatabaseAsync(name);
  try {
    await database.execAsync(`PRAGMA key = "x'${key}'"`);
    await database.execAsync('PRAGMA foreign_keys = ON; PRAGMA journal_mode = WAL;');
    await migrate(database);
  } catch (error) {
    await database.closeAsync();
    throw error;
  }

  activeDatabase = database;
  activeDatabaseName = name;
  return database;
}

export async function closeAccountDatabase(): Promise<void> {
  const database = activeDatabase;
  activeDatabase = null;
  activeDatabaseName = null;
  if (database) await database.closeAsync();
}

export async function deleteAccountDatabase(namespace: string): Promise<void> {
  const name = await databaseName(namespace);
  if (activeDatabaseName === name) await closeAccountDatabase();
  await SQLite.deleteDatabaseAsync(name);
}

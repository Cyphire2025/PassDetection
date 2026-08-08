import type * as SQLite from 'expo-sqlite';

export const ACCOUNT_DATABASE_VERSION = 16;

export type AccountTransactionRunner = (
  task: (transaction: SQLite.SQLiteDatabase) => Promise<void>,
) => Promise<void>;

export async function migrateAccountDatabase(
  database: SQLite.SQLiteDatabase,
  runTransaction: AccountTransactionRunner,
): Promise<boolean> {
  const result = await database.getFirstAsync<{ user_version: number }>('PRAGMA user_version');
  const currentVersion = result?.user_version ?? 0;

  if (currentVersion > ACCOUNT_DATABASE_VERSION) {
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
      await transaction.execAsync(`PRAGMA user_version = ${ACCOUNT_DATABASE_VERSION}`);
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

  return currentVersion < ACCOUNT_DATABASE_VERSION;
}

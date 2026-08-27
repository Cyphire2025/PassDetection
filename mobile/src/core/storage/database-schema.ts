import type * as SQLite from 'expo-sqlite';

import { DEFAULT_TRIP_TIME_ZONE } from '@/core/localization/time-zone';
import { MY_PHOTOS_STORAGE_SCHEMA_SQL } from '@/features/my-photos/data/my-photos-storage-schema';

import {
  ATTENDANCE_NEEDS_REVIEW_MIGRATION_SQL,
  CURRENT_PENDING_ACTIONS_SCHEMA_SQL,
  REJECTED_ATTENDANCE_MINIMIZATION_MIGRATION_SQL,
} from './database-attendance-queue-migrations';
import { CURRENT_ATTENDANCE_RECOVERY_SCHEMA_SQL } from './database-attendance-recovery-schema';
import { reconcileVersion26Schemas } from './database-schema-v26';

export const ACCOUNT_DATABASE_VERSION = 26;

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
    // New databases opt into bounded incremental reclaim before the first table allocates pages.
    // Existing databases are never subjected to the blocking full VACUUM required to retrofit it.
    await database.execAsync('PRAGMA auto_vacuum = INCREMENTAL');
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
          timezone TEXT NOT NULL DEFAULT '${DEFAULT_TRIP_TIME_ZONE}'
            CHECK (length(timezone) BETWEEN 1 AND 64 AND timezone = trim(timezone)),
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
          roster_projection_complete INTEGER NOT NULL DEFAULT 0
            CHECK (roster_projection_complete IN (0, 1)),
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
          last_opened_at TEXT,
          retention_class TEXT NOT NULL DEFAULT 'required'
            CHECK (retention_class IN ('required', 'evictable'))
        );
        CREATE INDEX IF NOT EXISTS idx_offline_files_eviction
          ON offline_files(
            account_namespace,
            retention_class,
            COALESCE(last_opened_at, downloaded_at),
            downloaded_at,
            encrypted_path
          )
          WHERE retention_class = 'evictable';

        CREATE TABLE IF NOT EXISTS vault_eviction_tombstones (
          encrypted_path TEXT PRIMARY KEY NOT NULL,
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL,
          document_id TEXT NOT NULL,
          version INTEGER NOT NULL,
          checksum_sha256 TEXT NOT NULL,
          encrypted_size_bytes INTEGER NOT NULL CHECK (encrypted_size_bytes > 0),
          created_at TEXT NOT NULL,
          last_attempt_at TEXT,
          attempt_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_vault_eviction_tombstones_account
          ON vault_eviction_tombstones(account_namespace, created_at, encrypted_path);

        CREATE TABLE IF NOT EXISTS storage_maintenance_state (
          singleton_id INTEGER PRIMARY KEY NOT NULL CHECK (singleton_id = 1),
          last_run_at_epoch_ms INTEGER NOT NULL CHECK (last_run_at_epoch_ms >= 0)
        );

        CREATE TABLE IF NOT EXISTS sync_runtime_state (
          account_namespace TEXT PRIMARY KEY NOT NULL,
          last_successful_full_sync_at_epoch_ms INTEGER NOT NULL
            CHECK (last_successful_full_sync_at_epoch_ms >= 0)
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
          attendance_token_hash TEXT
            CHECK (attendance_token_hash IS NULL OR (
              length(attendance_token_hash) = 64
              AND attendance_token_hash NOT GLOB '*[^0-9a-f]*'
            )),
          attendance_token_version INTEGER
            CHECK (attendance_token_version IS NULL OR attendance_token_version >= 1),
          attendance_token_state TEXT NOT NULL DEFAULT 'unknown'
            CHECK (attendance_token_state IN (
              'unknown', 'active', 'missing', 'inactive', 'revoked', 'expired'
            )),
          attendance_token_expires_at TEXT,
          attendance_token_updated_at TEXT,
          attendance_evidence_observed_at TEXT,
          attendance_evidence_valid_until TEXT,
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
        CREATE INDEX IF NOT EXISTS idx_coordinator_attendance_token_lookup
          ON coordinator_passengers(account_namespace, trip_id, attendance_token_hash)
          WHERE attendance_token_state = 'active' AND attendance_token_hash IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_coordinator_roster_order
          ON coordinator_passengers(
            account_namespace, trip_id, display_name COLLATE NOCASE, id
          );
        CREATE INDEX IF NOT EXISTS idx_coordinator_roster_rooming_order
          ON coordinator_passengers(
            account_namespace, trip_id, display_name COLLATE NOCASE, id
          )
          WHERE room_number IS NOT NULL AND length(trim(room_number)) > 0;
        CREATE INDEX IF NOT EXISTS idx_coordinator_roster_meals_order
          ON coordinator_passengers(
            account_namespace, trip_id, display_name COLLATE NOCASE, id
          )
          WHERE meal_preference IS NOT NULL AND length(trim(meal_preference)) > 0;

        CREATE VIRTUAL TABLE IF NOT EXISTS coordinator_passengers_fts USING fts5(
          display_name,
          employee_code,
          content='coordinator_passengers',
          content_rowid='rowid',
          tokenize='unicode61 remove_diacritics 2'
        );
        CREATE TRIGGER IF NOT EXISTS coordinator_passengers_fts_insert
          AFTER INSERT ON coordinator_passengers
        BEGIN
          INSERT INTO coordinator_passengers_fts(rowid, display_name, employee_code)
          VALUES (new.rowid, new.display_name, new.employee_code);
        END;
        CREATE TRIGGER IF NOT EXISTS coordinator_passengers_fts_delete
          AFTER DELETE ON coordinator_passengers
        BEGIN
          INSERT INTO coordinator_passengers_fts(
            coordinator_passengers_fts, rowid, display_name, employee_code
          ) VALUES ('delete', old.rowid, old.display_name, old.employee_code);
        END;
        CREATE TRIGGER IF NOT EXISTS coordinator_passengers_fts_update
          AFTER UPDATE OF display_name, employee_code ON coordinator_passengers
        BEGIN
          INSERT INTO coordinator_passengers_fts(
            coordinator_passengers_fts, rowid, display_name, employee_code
          ) VALUES ('delete', old.rowid, old.display_name, old.employee_code);
          INSERT INTO coordinator_passengers_fts(rowid, display_name, employee_code)
          VALUES (new.rowid, new.display_name, new.employee_code);
        END;

        CREATE TABLE IF NOT EXISTS local_roster_cursors (
          token TEXT PRIMARY KEY NOT NULL,
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          search_key TEXT NOT NULL,
          filter_key TEXT NOT NULL CHECK (filter_key IN ('all', 'rooming', 'meals')),
          last_display_name TEXT NOT NULL,
          last_passenger_id TEXT NOT NULL,
          expires_at_epoch_ms INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_local_roster_cursors_expiry
          ON local_roster_cursors(account_namespace, expires_at_epoch_ms);

        CREATE TABLE IF NOT EXISTS coordinator_roster_staging (
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          generation_id TEXT NOT NULL,
          item_index INTEGER NOT NULL CHECK (item_index >= 0),
          id TEXT NOT NULL,
          display_name TEXT NOT NULL,
          employee_code TEXT,
          attendance_status TEXT NOT NULL,
          attendance_token_hash TEXT,
          attendance_token_version INTEGER,
          attendance_token_state TEXT NOT NULL,
          attendance_token_expires_at TEXT,
          attendance_token_updated_at TEXT,
          attendance_evidence_observed_at TEXT,
          attendance_evidence_valid_until TEXT,
          room_number TEXT,
          meal_preference TEXT,
          has_alert INTEGER NOT NULL CHECK (has_alert IN (0, 1)),
          updated_at TEXT NOT NULL,
          PRIMARY KEY(account_namespace, trip_id, generation_id, id),
          UNIQUE(account_namespace, trip_id, generation_id, item_index)
        );
        CREATE INDEX IF NOT EXISTS idx_coordinator_roster_staging_page
          ON coordinator_roster_staging(
            account_namespace, trip_id, generation_id, item_index
          );

        CREATE TABLE IF NOT EXISTS sync_cursors (
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL,
          cursor INTEGER NOT NULL DEFAULT 0,
          access_generation INTEGER NOT NULL,
          last_synced_at TEXT,
          last_error_code TEXT,
          PRIMARY KEY(account_namespace, trip_id)
        );

        CREATE TABLE IF NOT EXISTS sync_rebase_staging (
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          generation_id TEXT NOT NULL,
          resource_type TEXT NOT NULL CHECK (resource_type IN (
            'manifest', 'itinerary', 'announcements', 'common_documents',
            'personal_documents', 'room', 'meals', 'qr', 'readiness',
            'roster', 'attendance_sessions'
          )),
          item_key TEXT NOT NULL,
          item_index INTEGER NOT NULL CHECK (item_index >= 0),
          payload_json TEXT NOT NULL,
          PRIMARY KEY(account_namespace, trip_id, generation_id, resource_type, item_key),
          UNIQUE(account_namespace, trip_id, generation_id, resource_type, item_index)
        );
        CREATE INDEX IF NOT EXISTS idx_sync_rebase_staging_page
          ON sync_rebase_staging(
            account_namespace, trip_id, generation_id, resource_type, item_index
          );

        ${CURRENT_PENDING_ACTIONS_SCHEMA_SQL}

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

        ${CURRENT_ATTENDANCE_RECOVERY_SCHEMA_SQL}

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
          scheduled_starts_at TEXT,
          scheduled_ends_at TEXT,
          schedule_timezone TEXT,
          schedule_version INTEGER NOT NULL DEFAULT 1 CHECK (schedule_version >= 1),
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_attendance_sessions_trip
          ON attendance_sessions(account_namespace, trip_id, status, started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_attendance_sessions_schedule
          ON attendance_sessions(
            account_namespace, trip_id, scheduled_starts_at, scheduled_ends_at
          );

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

        ${MY_PHOTOS_STORAGE_SCHEMA_SQL}
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

  if (currentVersion < 17) {
    await runTransaction(async (transaction) => {
      await transaction.execAsync(`
        CREATE TABLE IF NOT EXISTS sync_rebase_staging (
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          generation_id TEXT NOT NULL,
          resource_type TEXT NOT NULL CHECK (resource_type IN (
            'manifest', 'itinerary', 'announcements', 'common_documents',
            'personal_documents', 'room', 'meals', 'qr', 'readiness',
            'roster', 'attendance_sessions'
          )),
          item_key TEXT NOT NULL,
          item_index INTEGER NOT NULL CHECK (item_index >= 0),
          payload_json TEXT NOT NULL,
          PRIMARY KEY(account_namespace, trip_id, generation_id, resource_type, item_key),
          UNIQUE(account_namespace, trip_id, generation_id, resource_type, item_index)
        );
        CREATE INDEX IF NOT EXISTS idx_sync_rebase_staging_page
          ON sync_rebase_staging(
            account_namespace, trip_id, generation_id, resource_type, item_index
          );
        CREATE INDEX IF NOT EXISTS idx_pending_attendance_session
          ON pending_actions(
            account_namespace,
            trip_id,
            state,
            (CASE WHEN json_valid(payload_json)
              THEN json_extract(payload_json, '$.session_id') ELSE NULL END)
          )
          WHERE action_type = 'attendance.scan';
        PRAGMA user_version = 17;
      `);
    });
  }

  if (currentVersion < 18) {
    await runTransaction(async (transaction) => {
      await transaction.execAsync(`
        ALTER TABLE trips ADD COLUMN roster_projection_complete INTEGER NOT NULL DEFAULT 0
          CHECK (roster_projection_complete IN (0, 1));
        UPDATE trips
           SET roster_projection_complete = CASE
             WHEN roster_version >= 0 AND roster_version = advertised_roster_version THEN 1
             ELSE 0
           END;

        CREATE INDEX IF NOT EXISTS idx_coordinator_roster_order
          ON coordinator_passengers(
            account_namespace, trip_id, display_name COLLATE NOCASE, id
          );
        CREATE INDEX IF NOT EXISTS idx_coordinator_roster_rooming_order
          ON coordinator_passengers(
            account_namespace, trip_id, display_name COLLATE NOCASE, id
          )
          WHERE room_number IS NOT NULL AND length(trim(room_number)) > 0;
        CREATE INDEX IF NOT EXISTS idx_coordinator_roster_meals_order
          ON coordinator_passengers(
            account_namespace, trip_id, display_name COLLATE NOCASE, id
          )
          WHERE meal_preference IS NOT NULL AND length(trim(meal_preference)) > 0;

        CREATE VIRTUAL TABLE IF NOT EXISTS coordinator_passengers_fts USING fts5(
          display_name,
          employee_code,
          content='coordinator_passengers',
          content_rowid='rowid',
          tokenize='unicode61 remove_diacritics 2'
        );
        CREATE TRIGGER IF NOT EXISTS coordinator_passengers_fts_insert
          AFTER INSERT ON coordinator_passengers
        BEGIN
          INSERT INTO coordinator_passengers_fts(rowid, display_name, employee_code)
          VALUES (new.rowid, new.display_name, new.employee_code);
        END;
        CREATE TRIGGER IF NOT EXISTS coordinator_passengers_fts_delete
          AFTER DELETE ON coordinator_passengers
        BEGIN
          INSERT INTO coordinator_passengers_fts(
            coordinator_passengers_fts, rowid, display_name, employee_code
          ) VALUES ('delete', old.rowid, old.display_name, old.employee_code);
        END;
        CREATE TRIGGER IF NOT EXISTS coordinator_passengers_fts_update
          AFTER UPDATE OF display_name, employee_code ON coordinator_passengers
        BEGIN
          INSERT INTO coordinator_passengers_fts(
            coordinator_passengers_fts, rowid, display_name, employee_code
          ) VALUES ('delete', old.rowid, old.display_name, old.employee_code);
          INSERT INTO coordinator_passengers_fts(rowid, display_name, employee_code)
          VALUES (new.rowid, new.display_name, new.employee_code);
        END;
        INSERT INTO coordinator_passengers_fts(coordinator_passengers_fts) VALUES ('rebuild');

        CREATE TABLE IF NOT EXISTS local_roster_cursors (
          token TEXT PRIMARY KEY NOT NULL,
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          search_key TEXT NOT NULL,
          filter_key TEXT NOT NULL CHECK (filter_key IN ('all', 'rooming', 'meals')),
          last_display_name TEXT NOT NULL,
          last_passenger_id TEXT NOT NULL,
          expires_at_epoch_ms INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_local_roster_cursors_expiry
          ON local_roster_cursors(account_namespace, expires_at_epoch_ms);

        CREATE TABLE IF NOT EXISTS coordinator_roster_staging (
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          generation_id TEXT NOT NULL,
          item_index INTEGER NOT NULL CHECK (item_index >= 0),
          id TEXT NOT NULL,
          display_name TEXT NOT NULL,
          employee_code TEXT,
          attendance_status TEXT NOT NULL,
          room_number TEXT,
          meal_preference TEXT,
          has_alert INTEGER NOT NULL CHECK (has_alert IN (0, 1)),
          updated_at TEXT NOT NULL,
          PRIMARY KEY(account_namespace, trip_id, generation_id, id),
          UNIQUE(account_namespace, trip_id, generation_id, item_index)
        );
        CREATE INDEX IF NOT EXISTS idx_coordinator_roster_staging_page
          ON coordinator_roster_staging(
            account_namespace, trip_id, generation_id, item_index
          );
        PRAGMA user_version = 18;
      `);
    });
  }

  if (currentVersion < 19) {
    await runTransaction(async (transaction) => {
      await transaction.execAsync(`
        ALTER TABLE offline_files ADD COLUMN retention_class TEXT NOT NULL DEFAULT 'required'
          CHECK (retention_class IN ('required', 'evictable'));
        CREATE INDEX IF NOT EXISTS idx_offline_files_eviction
          ON offline_files(
            account_namespace,
            retention_class,
            COALESCE(last_opened_at, downloaded_at),
            downloaded_at,
            encrypted_path
          )
          WHERE retention_class = 'evictable';

        CREATE TABLE IF NOT EXISTS vault_eviction_tombstones (
          encrypted_path TEXT PRIMARY KEY NOT NULL,
          account_namespace TEXT NOT NULL,
          trip_id TEXT NOT NULL,
          document_id TEXT NOT NULL,
          version INTEGER NOT NULL,
          checksum_sha256 TEXT NOT NULL,
          encrypted_size_bytes INTEGER NOT NULL CHECK (encrypted_size_bytes > 0),
          created_at TEXT NOT NULL,
          last_attempt_at TEXT,
          attempt_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_vault_eviction_tombstones_account
          ON vault_eviction_tombstones(account_namespace, created_at, encrypted_path);

        CREATE TABLE IF NOT EXISTS storage_maintenance_state (
          singleton_id INTEGER PRIMARY KEY NOT NULL CHECK (singleton_id = 1),
          last_run_at_epoch_ms INTEGER NOT NULL CHECK (last_run_at_epoch_ms >= 0)
        );
        PRAGMA user_version = 19;
      `);
    });
  }

  if (currentVersion < 20) {
    await runTransaction(async (transaction) => {
      await transaction.execAsync(`
        ALTER TABLE trips ADD COLUMN timezone TEXT NOT NULL DEFAULT '${DEFAULT_TRIP_TIME_ZONE}'
          CHECK (length(timezone) BETWEEN 1 AND 64 AND timezone = trim(timezone));
        PRAGMA user_version = 20;
      `);
    });
  }

  if (currentVersion < 21) {
    await runTransaction(async (transaction) => {
      await transaction.execAsync(`
        ALTER TABLE coordinator_passengers ADD COLUMN attendance_token_hash TEXT
          CHECK (attendance_token_hash IS NULL OR (
            length(attendance_token_hash) = 64
            AND attendance_token_hash NOT GLOB '*[^0-9a-f]*'
          ));
        ALTER TABLE coordinator_passengers ADD COLUMN attendance_token_version INTEGER
          CHECK (attendance_token_version IS NULL OR attendance_token_version >= 1);
        ALTER TABLE coordinator_passengers ADD COLUMN attendance_token_state TEXT NOT NULL DEFAULT 'unknown'
          CHECK (attendance_token_state IN (
            'unknown', 'active', 'missing', 'inactive', 'revoked', 'expired'
          ));
        ALTER TABLE coordinator_passengers ADD COLUMN attendance_token_expires_at TEXT;
        ALTER TABLE coordinator_passengers ADD COLUMN attendance_token_updated_at TEXT;
        ALTER TABLE coordinator_passengers ADD COLUMN attendance_evidence_observed_at TEXT;
        ALTER TABLE coordinator_passengers ADD COLUMN attendance_evidence_valid_until TEXT;

        ALTER TABLE coordinator_roster_staging ADD COLUMN attendance_token_hash TEXT;
        ALTER TABLE coordinator_roster_staging ADD COLUMN attendance_token_version INTEGER;
        ALTER TABLE coordinator_roster_staging ADD COLUMN attendance_token_state TEXT NOT NULL DEFAULT 'unknown';
        ALTER TABLE coordinator_roster_staging ADD COLUMN attendance_token_expires_at TEXT;
        ALTER TABLE coordinator_roster_staging ADD COLUMN attendance_token_updated_at TEXT;
        ALTER TABLE coordinator_roster_staging ADD COLUMN attendance_evidence_observed_at TEXT;
        ALTER TABLE coordinator_roster_staging ADD COLUMN attendance_evidence_valid_until TEXT;

        CREATE INDEX IF NOT EXISTS idx_coordinator_attendance_token_lookup
          ON coordinator_passengers(account_namespace, trip_id, attendance_token_hash)
          WHERE attendance_token_state = 'active' AND attendance_token_hash IS NOT NULL;

        DELETE FROM coordinator_roster_staging;
        UPDATE trips
           SET roster_version = -1, roster_projection_complete = 0
         WHERE role = 'coordinator';
        PRAGMA user_version = 21;
      `);
    });
  }

  if (currentVersion < 22) {
    await runTransaction(async (transaction) => {
      await transaction.execAsync(`
        CREATE TABLE IF NOT EXISTS sync_runtime_state (
          account_namespace TEXT PRIMARY KEY NOT NULL,
          last_successful_full_sync_at_epoch_ms INTEGER NOT NULL
            CHECK (last_successful_full_sync_at_epoch_ms >= 0)
        );
        PRAGMA user_version = 22;
      `);
    });
  }

  if (currentVersion < 23) {
    await runTransaction(async (transaction) => {
      await transaction.execAsync(ATTENDANCE_NEEDS_REVIEW_MIGRATION_SQL);
    });
  }

  if (currentVersion < 24) {
    await runTransaction(async (transaction) => {
      await transaction.execAsync(REJECTED_ATTENDANCE_MINIMIZATION_MIGRATION_SQL);
    });
  }

  if (currentVersion < 25) {
    await runTransaction(async (transaction) => {
      await transaction.execAsync(`
        ${MY_PHOTOS_STORAGE_SCHEMA_SQL}
        PRAGMA user_version = 25;
      `);
    });
  }

  if (currentVersion < 26) {
    await runTransaction(reconcileVersion26Schemas);
  }

  return currentVersion < ACCOUNT_DATABASE_VERSION;
}

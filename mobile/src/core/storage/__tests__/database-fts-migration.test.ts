import type { DatabaseSync } from 'node:sqlite';

import {
  ACCOUNT_DATABASE_VERSION,
  migrateAccountDatabase,
} from '../database-schema';

const ACCOUNT = 'agency.coordinator';
const TRIP_ID = '11111111-1111-4111-8111-111111111111';

const DatabaseSyncConstructor = (() => {
  try {
    return (jest.requireActual('node:sqlite') as typeof import('node:sqlite')).DatabaseSync;
  } catch {
    return null;
  }
})();
const sqliteTest = DatabaseSyncConstructor === null ? test.skip : test;

sqliteTest('fresh current databases enable incremental reclaim before allocating schema pages', async () => {
  if (DatabaseSyncConstructor === null) return;
  const database = new DatabaseSyncConstructor(':memory:');
  try {
    await migrateAccountDatabase(
      {
        getFirstAsync: async (sql: string) => database.prepare(sql).get(),
        execAsync: async (sql: string) => database.exec(sql),
      } as never,
      async (operation) => {
        database.exec('BEGIN IMMEDIATE');
        try {
          await operation({
            execAsync: async (sql: string) => database.exec(sql),
            getAllAsync: async (sql: string) => database.prepare(sql).all(),
          } as never);
          database.exec('COMMIT');
        } catch (error) {
          database.exec('ROLLBACK');
          throw error;
        }
      },
    );

    expect(database.prepare('PRAGMA user_version').get()).toMatchObject({
      user_version: ACCOUNT_DATABASE_VERSION,
    });
    expect(database.prepare('PRAGMA auto_vacuum').get()).toMatchObject({ auto_vacuum: 2 });
    expect(database.prepare(
      `SELECT name FROM sqlite_master
        WHERE type = 'table' AND name IN (
          'vault_eviction_tombstones', 'storage_maintenance_state'
        ) ORDER BY name`,
    ).all().map((row) => row.name)).toEqual([
      'storage_maintenance_state',
      'vault_eviction_tombstones',
    ]);
  } finally {
    database.close();
  }
});

function createVersion17Database(): DatabaseSync {
  if (DatabaseSyncConstructor === null) {
    throw new Error('node:sqlite is unavailable in this Node.js runtime.');
  }
  const database = new DatabaseSyncConstructor(':memory:');
  database.exec(`
    PRAGMA foreign_keys = ON;
    CREATE TABLE trips (
      id TEXT PRIMARY KEY NOT NULL,
      account_namespace TEXT NOT NULL,
      role TEXT NOT NULL,
      roster_version INTEGER NOT NULL DEFAULT -1,
      advertised_roster_version INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE attendance_sessions (
      id TEXT PRIMARY KEY NOT NULL,
      account_namespace TEXT NOT NULL,
      trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
      name TEXT NOT NULL,
      status TEXT NOT NULL,
      scanned_count INTEGER NOT NULL,
      assigned_count INTEGER NOT NULL,
      started_at TEXT,
      completed_at TEXT,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE coordinator_passengers (
      id TEXT NOT NULL,
      account_namespace TEXT NOT NULL,
      trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
      display_name TEXT NOT NULL,
      employee_code TEXT,
      attendance_status TEXT NOT NULL,
      room_number TEXT,
      meal_preference TEXT,
      has_alert INTEGER NOT NULL DEFAULT 0,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(account_namespace, trip_id, id)
    );
    CREATE TABLE offline_files (
      document_id TEXT PRIMARY KEY NOT NULL,
      account_namespace TEXT NOT NULL,
      trip_id TEXT NOT NULL,
      version INTEGER NOT NULL,
      encrypted_path TEXT NOT NULL,
      checksum_sha256 TEXT NOT NULL,
      encrypted_size_bytes INTEGER NOT NULL,
      downloaded_at TEXT NOT NULL,
      last_opened_at TEXT
    );
    CREATE TABLE pending_actions (
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
    CREATE INDEX idx_pending_drain
      ON pending_actions(account_namespace, state, next_attempt_at, created_at);
    CREATE UNIQUE INDEX idx_pending_action_dedupe
      ON pending_actions(account_namespace, trip_id, action_type, dedupe_key)
      WHERE dedupe_key IS NOT NULL;
    CREATE INDEX idx_pending_attendance_session
      ON pending_actions(
        account_namespace,
        trip_id,
        action_type,
        json_extract(payload_json, '$.session_id'),
        state,
        created_at
      )
      WHERE action_type = 'attendance.scan';
    INSERT INTO trips(id, account_namespace, role, roster_version, advertised_roster_version)
    VALUES ('${TRIP_ID}', '${ACCOUNT}', 'coordinator', 7, 7);
    INSERT INTO coordinator_passengers(
      id, account_namespace, trip_id, display_name, employee_code,
      attendance_status, room_number, meal_preference, has_alert, updated_at
    ) VALUES (
      'passenger-existing', '${ACCOUNT}', '${TRIP_ID}', 'José Existing', 'EMP-001',
      'not_marked', NULL, NULL, 0, '2030-01-01T00:00:00.000Z'
    );
    PRAGMA user_version = 17;
  `);
  return database;
}

async function migrateVersion17(database: DatabaseSync): Promise<void> {
  await migrateAccountDatabase(
    {
      getFirstAsync: async (sql: string) => database.prepare(sql).get(),
    } as never,
    async (operation) => {
      database.exec('BEGIN IMMEDIATE');
      try {
        await operation({
          execAsync: async (sql: string) => database.exec(sql),
          getAllAsync: async (sql: string) => database.prepare(sql).all(),
        } as never);
        database.exec('COMMIT');
      } catch (error) {
        database.exec('ROLLBACK');
        throw error;
      }
    },
  );
}

function matchingIds(database: DatabaseSync, query: string): string[] {
  return database.prepare(
    `SELECT passenger.id
       FROM coordinator_passengers_fts
       JOIN coordinator_passengers AS passenger
         ON passenger.rowid = coordinator_passengers_fts.rowid
      WHERE coordinator_passengers_fts MATCH ?
      ORDER BY passenger.id`,
  ).all(query).map((row) => String(row.id));
}

sqliteTest('v17 migration backfills FTS and storage while invalidating legacy roster trust', async () => {
  const database = createVersion17Database();
  try {
    await migrateVersion17(database);

    expect(database.prepare('PRAGMA user_version').get()).toMatchObject({
      user_version: ACCOUNT_DATABASE_VERSION,
    });
    expect(database.prepare(
      'SELECT roster_projection_complete FROM trips WHERE id = ?',
    ).get(TRIP_ID)).toMatchObject({ roster_projection_complete: 0 });
    expect(matchingIds(database, '"jose"*')).toEqual(['passenger-existing']);
    expect(database.prepare(
      `SELECT name FROM sqlite_master
        WHERE type = 'table' AND name IN ('local_roster_cursors', 'coordinator_roster_staging')
        ORDER BY name`,
    ).all().map((row) => row.name)).toEqual([
      'coordinator_roster_staging',
      'local_roster_cursors',
    ]);
    expect(database.prepare('PRAGMA table_info(offline_files)').all().map(
      (row) => row.name,
    )).toContain('retention_class');
  } finally {
    database.close();
  }
});

sqliteTest('current FTS triggers track insert, searchable-column update, and delete', async () => {
  const database = createVersion17Database();
  try {
    await migrateVersion17(database);
    database.prepare(
      `INSERT INTO coordinator_passengers(
        id, account_namespace, trip_id, display_name, employee_code,
        attendance_status, room_number, meal_preference, has_alert, updated_at
      ) VALUES (?, ?, ?, ?, ?, 'not_marked', NULL, NULL, 0, ?)`,
    ).run(
      'passenger-trigger',
      ACCOUNT,
      TRIP_ID,
      'Zoë Trigger',
      'OPS-900',
      '2030-01-01T00:00:00.000Z',
    );
    expect(matchingIds(database, '"zoe"*')).toEqual(['passenger-trigger']);
    expect(matchingIds(database, '"ops"*')).toEqual(['passenger-trigger']);

    database.prepare(
      `UPDATE coordinator_passengers
          SET display_name = 'Renamed Passenger', employee_code = 'NEW-900'
        WHERE account_namespace = ? AND trip_id = ? AND id = ?`,
    ).run(ACCOUNT, TRIP_ID, 'passenger-trigger');
    expect(matchingIds(database, '"zoe"*')).toEqual([]);
    expect(matchingIds(database, '"ren"*')).toEqual(['passenger-trigger']);

    database.prepare(
      `DELETE FROM coordinator_passengers
        WHERE account_namespace = ? AND trip_id = ? AND id = ?`,
    ).run(ACCOUNT, TRIP_ID, 'passenger-trigger');
    expect(matchingIds(database, '"ren"*')).toEqual([]);
  } finally {
    database.close();
  }
});

import type { DatabaseSync } from 'node:sqlite';

import {
  ACCOUNT_DATABASE_VERSION,
  migrateAccountDatabase,
} from '../database-schema';

const ACCOUNT = 'agency-coordinator.coordinator-one';
const TRIP_ID = '11111111-1111-4111-8111-111111111111';
const EVENT_ID = '22222222-2222-4222-8222-222222222222';
const REJECTED_EVENT_ID = '44444444-4444-4444-8444-444444444444';
const INSERTED_REJECTED_EVENT_ID = '55555555-5555-4555-8555-555555555555';
const REJECTED_NOTIFICATION_EVENT_ID = '66666666-6666-4666-8666-666666666666';
const SIGNED_QR = 'pdatt:0000000000000000000000000000000000000000001';

const DatabaseSyncConstructor = (() => {
  try {
    return (jest.requireActual('node:sqlite') as typeof import('node:sqlite')).DatabaseSync;
  } catch {
    return null;
  }
})();
const sqliteTest = DatabaseSyncConstructor === null ? test.skip : test;

function createVersion22Database(): DatabaseSync {
  if (DatabaseSyncConstructor === null) {
    throw new Error('node:sqlite is unavailable in this Node.js runtime.');
  }
  const database = new DatabaseSyncConstructor(':memory:');
  database.exec(`
    PRAGMA foreign_keys = ON;
    CREATE TABLE trips (id TEXT PRIMARY KEY NOT NULL);
    INSERT INTO trips(id) VALUES ('${TRIP_ID}');
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
      ON pending_actions(account_namespace, trip_id, state, next_attempt_at, created_at);
    CREATE UNIQUE INDEX idx_pending_action_dedupe
      ON pending_actions(account_namespace, trip_id, action_type, dedupe_key)
      WHERE dedupe_key IS NOT NULL;
    CREATE INDEX idx_pending_attendance_session
      ON pending_actions(
        account_namespace,
        trip_id,
        state,
        (CASE WHEN json_valid(payload_json)
          THEN json_extract(payload_json, '$.session_id') ELSE NULL END)
      )
      WHERE action_type = 'attendance.scan';
    INSERT INTO pending_actions(
      idempotency_key, account_namespace, trip_id, action_type, dedupe_key,
      payload_json, base_version, state, attempt_count, next_attempt_at,
      last_error_code, created_at, updated_at
    ) VALUES (
      '${EVENT_ID}', '${ACCOUNT}', '${TRIP_ID}', 'attendance.scan', 'dedupe-one',
      '{"session_id":"33333333-3333-4333-8333-333333333333","signed_qr":"${SIGNED_QR}"}', NULL,
      'retryable', 3, '2030-01-01T00:01:00.000Z', 'RATE_LIMITED',
      '2030-01-01T00:00:00.000Z', '2030-01-01T00:00:01.000Z'
    );
    INSERT INTO pending_actions(
      idempotency_key, account_namespace, trip_id, action_type, dedupe_key,
      payload_json, base_version, state, attempt_count, next_attempt_at,
      last_error_code, created_at, updated_at
    ) VALUES (
      '${REJECTED_EVENT_ID}', '${ACCOUNT}', '${TRIP_ID}', 'attendance.scan', 'dedupe-rejected',
      '{"session_id":"33333333-3333-4333-8333-333333333333","signed_qr":"${SIGNED_QR}"}', NULL,
      'rejected', 1, NULL, 'QR_REVOKED',
      '2030-01-01T00:00:00.000Z', '2030-01-01T00:00:02.000Z'
    );
    INSERT INTO pending_actions(
      idempotency_key, account_namespace, trip_id, action_type, dedupe_key,
      payload_json, base_version, state, attempt_count, next_attempt_at,
      last_error_code, created_at, updated_at
    ) VALUES (
      '${REJECTED_NOTIFICATION_EVENT_ID}', '${ACCOUNT}', '${TRIP_ID}',
      'notification.read', NULL, '{"notification_id":"notice-one"}', NULL,
      'rejected', 1, NULL, 'NOTIFICATION_GONE',
      '2030-01-01T00:00:00.000Z', '2030-01-01T00:00:02.000Z'
    );
    PRAGMA user_version = 22;
  `);
  return database;
}

async function migrate(database: DatabaseSync): Promise<void> {
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

sqliteTest('v24 preserves retriable scans and minimizes every terminal attendance payload', async () => {
  const database = createVersion22Database();
  try {
    await migrate(database);

    expect(database.prepare('PRAGMA user_version').get()).toMatchObject({
      user_version: ACCOUNT_DATABASE_VERSION,
    });
    expect(database.prepare(
      `SELECT state, payload_json, attempt_count, refresh_attempt_count,
              next_attempt_at, last_error_code
         FROM pending_actions WHERE idempotency_key = ?`,
    ).get(EVENT_ID)).toMatchObject({
      state: 'retryable',
      payload_json: expect.stringContaining(SIGNED_QR),
      attempt_count: 3,
      refresh_attempt_count: 0,
      next_attempt_at: '2030-01-01T00:01:00.000Z',
      last_error_code: 'RATE_LIMITED',
    });
    expect(database.prepare(
      `SELECT payload_json, dedupe_key, last_error_code
         FROM pending_actions WHERE idempotency_key = ?`,
    ).get(REJECTED_EVENT_ID)).toMatchObject({
      payload_json: '{}',
      dedupe_key: 'dedupe-rejected',
      last_error_code: 'QR_REVOKED',
    });
    expect(database.prepare(
      'SELECT payload_json FROM pending_actions WHERE idempotency_key = ?',
    ).get(REJECTED_NOTIFICATION_EVENT_ID)).toMatchObject({
      payload_json: '{"notification_id":"notice-one"}',
    });

    database.prepare(
      `UPDATE pending_actions
          SET state = 'needs_review', refresh_attempt_count = 1
        WHERE idempotency_key = ?`,
    ).run(EVENT_ID);
    expect(database.prepare(
      `SELECT state, payload_json, refresh_attempt_count
         FROM pending_actions WHERE idempotency_key = ?`,
    ).get(EVENT_ID)).toMatchObject({
      state: 'needs_review',
      payload_json: expect.stringContaining(SIGNED_QR),
      refresh_attempt_count: 1,
    });
    expect(() => database.prepare(
      'UPDATE pending_actions SET refresh_attempt_count = 2 WHERE idempotency_key = ?',
    ).run(EVENT_ID)).toThrow();

    database.prepare(
      "UPDATE pending_actions SET state = 'rejected' WHERE idempotency_key = ?",
    ).run(EVENT_ID);
    expect(database.prepare(
      'SELECT payload_json FROM pending_actions WHERE idempotency_key = ?',
    ).get(EVENT_ID)).toMatchObject({ payload_json: '{}' });

    database.prepare(
      'UPDATE pending_actions SET payload_json = ? WHERE idempotency_key = ?',
    ).run(JSON.stringify({ signed_qr: `pdatt:${'A'.repeat(43)}` }), EVENT_ID);
    expect(database.prepare(
      'SELECT payload_json FROM pending_actions WHERE idempotency_key = ?',
    ).get(EVENT_ID)).toMatchObject({ payload_json: '{}' });

    database.prepare(
      `INSERT INTO pending_actions(
         idempotency_key, account_namespace, trip_id, action_type, dedupe_key,
         payload_json, base_version, state, attempt_count, refresh_attempt_count,
         next_attempt_at, last_error_code, created_at, updated_at
       ) VALUES (?, ?, ?, 'attendance.scan', ?, ?, NULL, 'rejected', 1, 0,
                 NULL, 'INVALID_LOCAL_PAYLOAD', ?, ?)`,
    ).run(
      INSERTED_REJECTED_EVENT_ID,
      ACCOUNT,
      TRIP_ID,
      'dedupe-inserted-rejected',
      JSON.stringify({ signed_qr: `pdatt:${'B'.repeat(43)}` }),
      '2030-01-01T00:00:03.000Z',
      '2030-01-01T00:00:04.000Z',
    );
    expect(database.prepare(
      'SELECT payload_json FROM pending_actions WHERE idempotency_key = ?',
    ).get(INSERTED_REJECTED_EVENT_ID)).toMatchObject({ payload_json: '{}' });

    expect(database.prepare(
      `SELECT name FROM sqlite_master
        WHERE type = 'index' AND name LIKE 'idx_pending_%'
        ORDER BY name`,
    ).all().map((row) => row.name)).toEqual([
      'idx_pending_action_dedupe',
      'idx_pending_attendance_session',
      'idx_pending_drain',
    ]);
    expect(database.prepare(
      `SELECT name FROM sqlite_master
        WHERE type = 'trigger' AND name LIKE 'minimize_rejected_attendance_%'
        ORDER BY name`,
    ).all().map((row) => row.name)).toEqual([
      'minimize_rejected_attendance_insert',
      'minimize_rejected_attendance_update',
    ]);
  } finally {
    database.close();
  }
});

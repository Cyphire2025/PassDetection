import type { DatabaseSync } from 'node:sqlite';

import { migrateAccountDatabase } from '@/core/storage/database-schema';

import {
  normalizeRosterSearch,
  queryLocalRoster,
} from '../local-roster-search';

const ACCOUNT = 'agency.coordinator-a';
const OTHER_ACCOUNT = 'agency.coordinator-b';
const TRIP_ID = '11111111-1111-4111-8111-111111111111';
const OTHER_TRIP_ID = '22222222-2222-4222-8222-222222222222';

const DatabaseSyncConstructor = (() => {
  try {
    return (jest.requireActual('node:sqlite') as typeof import('node:sqlite')).DatabaseSync;
  } catch {
    return null;
  }
})();
const sqliteTest = DatabaseSyncConstructor === null ? test.skip : test;

function sqliteAdapter(database: DatabaseSync) {
  return {
    getAllAsync: async (sql: string, ...parameters: unknown[]) => (
      database.prepare(sql).all(...(parameters as never[]))
    ),
    getFirstAsync: async (sql: string, ...parameters: unknown[]) => (
      database.prepare(sql).get(...(parameters as never[])) ?? null
    ),
    runAsync: async (sql: string, ...parameters: unknown[]) => {
      const result = database.prepare(sql).run(...(parameters as never[]));
      return {
        changes: Number(result.changes),
        lastInsertRowId: Number(result.lastInsertRowid),
      };
    },
  };
}

async function createDatabase(): Promise<DatabaseSync> {
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
    -- Later migrations extend this long-lived v17 table. Keep the focused roster fixture structurally
    -- faithful so the real ordered migration can run without weakening production SQL.
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
    VALUES
      ('${TRIP_ID}', '${ACCOUNT}', 'coordinator', 7, 7),
      ('${OTHER_TRIP_ID}', '${OTHER_ACCOUNT}', 'coordinator', 7, 7);
    PRAGMA user_version = 17;
  `);
  await migrateAccountDatabase(
    {
      getFirstAsync: async (sql: string) => database.prepare(sql).get(),
    } as never,
    async (operation) => {
      database.exec('BEGIN IMMEDIATE');
      try {
        await operation({ execAsync: async (sql: string) => database.exec(sql) } as never);
        database.exec('COMMIT');
      } catch (error) {
        database.exec('ROLLBACK');
        throw error;
      }
    },
  );
  // v21 intentionally invalidates legacy coordinator roster trust. These
  // search tests model a subsequent successful evidence-aware replacement.
  database.exec(`
    UPDATE trips
       SET roster_version = 7,
           advertised_roster_version = 7,
           roster_projection_complete = 1;
  `);
  return database;
}

function insertPassenger(database: DatabaseSync, options: Readonly<{
  account?: string;
  employeeCode?: string | null;
  hasAlert?: boolean;
  id: string;
  meal?: string | null;
  name: string;
  room?: string | null;
  tripId?: string;
}>): void {
  database.prepare(
    `INSERT INTO coordinator_passengers(
      id, account_namespace, trip_id, display_name, employee_code, attendance_status,
      room_number, meal_preference, has_alert, updated_at
    ) VALUES (?, ?, ?, ?, ?, 'not_marked', ?, ?, ?, '2030-01-01T00:00:00.000Z')`,
  ).run(
    options.id,
    options.account ?? ACCOUNT,
    options.tripId ?? TRIP_ID,
    options.name,
    options.employeeCode ?? null,
    options.room ?? null,
    options.meal ?? null,
    options.hasAlert ? 1 : 0,
  );
}

function cursorFactory(): () => string {
  let sequence = 0;
  return () => {
    sequence += 1;
    return `00000000-0000-4000-8000-${String(sequence).padStart(12, '0')}`;
  };
}

test('normalizes Unicode into quoted FTS prefix terms and neutralizes hostile syntax', () => {
  expect(normalizeRosterSearch('  José   O\'Connor  ')).toEqual({
    ftsQuery: '"josé"* AND "o"* AND "connor"*',
    matchesNothing: false,
    searchKey: 'josé\u001fo\u001fconnor',
  });
  expect(normalizeRosterSearch('") OR * employee_code:*')).toEqual({
    ftsQuery: '"or"* AND "employee"* AND "code"*',
    matchesNothing: false,
    searchKey: 'or\u001femployee\u001fcode',
  });
  expect(normalizeRosterSearch('***')).toMatchObject({
    ftsQuery: null,
    matchesNothing: true,
  });
});

sqliteTest('uses opaque scoped keyset cursors without exposing names or passenger identifiers', async () => {
  const database = await createDatabase();
  try {
    database.exec('BEGIN');
    for (let index = 0; index < 150; index += 1) {
      insertPassenger(database, {
        id: `passenger-${String(index).padStart(4, '0')}`,
        name: 'Duplicate Name',
      });
    }
    insertPassenger(database, {
      account: OTHER_ACCOUNT,
      id: 'other-private-passenger',
      name: 'Duplicate Name',
      tripId: OTHER_TRIP_ID,
    });
    database.exec('COMMIT');

    const adapter = sqliteAdapter(database);
    const createCursorToken = cursorFactory();
    const first = await queryLocalRoster({
      accountNamespace: ACCOUNT,
      createCursorToken,
      database: adapter as never,
      tripId: TRIP_ID,
    });
    expect(first.items).toHaveLength(100);
    expect(first.total).toBe(150);
    expect(first.next_cursor).toMatch(/^local:v1:[0-9a-f-]{36}$/);
    expect(first.next_cursor).not.toContain('Duplicate');
    expect(first.next_cursor).not.toContain('passenger');
    expect(first.next_cursor).not.toContain(ACCOUNT);
    expect(first.projectionCompleteness).toEqual({
      advertisedRosterVersion: 7,
      appliedRosterVersion: 7,
      fullReplacementCompleted: true,
      isComplete: true,
    });

    insertPassenger(database, { id: 'passenger-0050a', name: 'Duplicate Name' });
    insertPassenger(database, { id: 'passenger-0120a', name: 'Duplicate Name' });
    const second = await queryLocalRoster({
      accountNamespace: ACCOUNT,
      createCursorToken,
      cursor: first.next_cursor,
      database: adapter as never,
      tripId: TRIP_ID,
    });
    const firstIds = new Set(first.items.map((item) => item.id));
    expect(second.items.every((item) => !firstIds.has(item.id))).toBe(true);
    expect(second.items.map((item) => item.id)).not.toContain('passenger-0050a');
    expect(second.items.map((item) => item.id)).toContain('passenger-0120a');
    expect(second.items.map((item) => item.id)).not.toContain('other-private-passenger');

    await expect(queryLocalRoster({
      accountNamespace: ACCOUNT,
      cursor: first.next_cursor,
      database: adapter as never,
      search: 'different search',
      tripId: TRIP_ID,
    })).rejects.toThrow('invalid for this query');
    await expect(queryLocalRoster({
      accountNamespace: OTHER_ACCOUNT,
      cursor: first.next_cursor,
      database: adapter as never,
      tripId: OTHER_TRIP_ID,
    })).rejects.toThrow('invalid for this query');
  } finally {
    database.close();
  }
});

sqliteTest('performs Unicode prefix search while hostile FTS input stays data, not grammar', async () => {
  const database = await createDatabase();
  try {
    insertPassenger(database, {
      employeeCode: 'OPS-900',
      id: 'jose',
      name: 'José O\'Connor',
    });
    insertPassenger(database, {
      account: OTHER_ACCOUNT,
      employeeCode: 'OPS-901',
      id: 'other-jose',
      name: 'José Private',
      tripId: OTHER_TRIP_ID,
    });
    const adapter = sqliteAdapter(database);
    const prefix = await queryLocalRoster({
      accountNamespace: ACCOUNT,
      database: adapter as never,
      search: 'jos',
      tripId: TRIP_ID,
    });
    expect(prefix.items.map((item) => item.id)).toEqual(['jose']);

    const substring = await queryLocalRoster({
      accountNamespace: ACCOUNT,
      database: adapter as never,
      search: 'osé',
      tripId: TRIP_ID,
    });
    expect(substring.items).toEqual([]);

    await expect(queryLocalRoster({
      accountNamespace: ACCOUNT,
      database: adapter as never,
      search: '") OR * employee_code:*',
      tripId: TRIP_ID,
    })).resolves.toMatchObject({ items: [], total: 0 });
  } finally {
    database.close();
  }
});

sqliteTest('applies rooming and meal filters before count and keyset pagination', async () => {
  const database = await createDatabase();
  try {
    database.exec('BEGIN');
    for (let index = 0; index < 260; index += 1) {
      insertPassenger(database, {
        id: `filtered-${String(index).padStart(4, '0')}`,
        meal: index >= 210 ? 'Vegetarian' : null,
        name: `Passenger ${String(index).padStart(4, '0')}`,
        room: index >= 150 ? `R-${index}` : null,
      });
    }
    database.exec('COMMIT');
    const adapter = sqliteAdapter(database);
    const createCursorToken = cursorFactory();

    const roomingFirst = await queryLocalRoster({
      accountNamespace: ACCOUNT,
      createCursorToken,
      database: adapter as never,
      filter: 'rooming',
      tripId: TRIP_ID,
    });
    expect(roomingFirst.items).toHaveLength(100);
    expect(roomingFirst.items[0]?.id).toBe('filtered-0150');
    expect(roomingFirst.total).toBe(110);
    const roomingSecond = await queryLocalRoster({
      accountNamespace: ACCOUNT,
      createCursorToken,
      cursor: roomingFirst.next_cursor,
      database: adapter as never,
      filter: 'rooming',
      tripId: TRIP_ID,
    });
    expect(roomingSecond.items).toHaveLength(10);

    const meals = await queryLocalRoster({
      accountNamespace: ACCOUNT,
      database: adapter as never,
      filter: 'meals',
      tripId: TRIP_ID,
    });
    expect(meals.items).toHaveLength(50);
    expect(meals.items[0]?.id).toBe('filtered-0210');
    expect(meals.total).toBe(50);

    await expect(queryLocalRoster({
      accountNamespace: ACCOUNT,
      cursor: roomingFirst.next_cursor,
      database: adapter as never,
      filter: 'meals',
      tripId: TRIP_ID,
    })).rejects.toThrow('invalid for this query');

    database.prepare(
      'UPDATE trips SET advertised_roster_version = 8 WHERE account_namespace = ? AND id = ?',
    ).run(ACCOUNT, TRIP_ID);
    const incomplete = await queryLocalRoster({
      accountNamespace: ACCOUNT,
      createCursorToken,
      database: adapter as never,
      tripId: TRIP_ID,
    });
    expect(incomplete.projectionCompleteness).toEqual({
      advertisedRosterVersion: 8,
      appliedRosterVersion: 7,
      fullReplacementCompleted: true,
      isComplete: false,
    });
  } finally {
    database.close();
  }
});

sqliteTest('rejects malformed and expired local cursors fail closed', async () => {
  const database = await createDatabase();
  try {
    const adapter = sqliteAdapter(database);
    await expect(queryLocalRoster({
      accountNamespace: ACCOUNT,
      cursor: 'local:100',
      database: adapter as never,
      tripId: TRIP_ID,
    })).rejects.toThrow('invalid for this query');

    for (let index = 0; index < 101; index += 1) {
      insertPassenger(database, { id: `expiry-${index}`, name: `Expiry ${index}` });
    }
    const first = await queryLocalRoster({
      accountNamespace: ACCOUNT,
      createCursorToken: cursorFactory(),
      database: adapter as never,
      nowMs: 1_000,
      tripId: TRIP_ID,
    });
    await expect(queryLocalRoster({
      accountNamespace: ACCOUNT,
      cursor: first.next_cursor,
      database: adapter as never,
      nowMs: 1_000 + (25 * 60 * 60 * 1_000),
      tripId: TRIP_ID,
    })).rejects.toThrow('invalid for this query');
  } finally {
    database.close();
  }
});

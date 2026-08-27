import type { DatabaseSync } from 'node:sqlite';

import { apiRequest } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';
import { migrateAccountDatabase } from '@/core/storage/database-schema';

import { loadRoster, syncFullRoster } from '../coordinator-repository';
import { MOBILE_GROUP_PASSENGER_CAPACITY } from '../full-roster-sync';

jest.mock('@/core/api/client', () => {
  const actual = jest.requireActual('@/core/api/client');
  return { ...actual, apiRequest: jest.fn() };
});
jest.mock('@/core/storage/database', () => ({
  openAccountDatabase: jest.fn(),
  withAccountTransaction: jest.fn(),
}));
jest.mock('expo-crypto', () => ({
  randomUUID: jest.fn(() => '55555555-5555-4555-8555-555555555555'),
}));

const TRIP_ID = '11111111-1111-4111-8111-111111111111';
const AGENCY_ID = '22222222-2222-4222-8222-222222222222';
const PRINCIPAL_ID = '33333333-3333-4333-8333-333333333333';

const DatabaseSyncConstructor = (() => {
  try {
    return (jest.requireActual('node:sqlite') as typeof import('node:sqlite')).DatabaseSync;
  } catch {
    return null;
  }
})();
const sqliteTest = DatabaseSyncConstructor === null ? test.skip : test;

const mockedApiRequest = jest.mocked(apiRequest);
const mockedOpenDatabase = jest.mocked(openAccountDatabase);
const mockedWithTransaction = jest.mocked(withAccountTransaction);

function passenger(index: number) {
  const observedAt = '2029-01-01T00:00:00.000Z';
  return {
    id: `passenger-${String(index).padStart(5, '0')}`,
    display_name: `Passenger ${String(index).padStart(5, '0')}`,
    employee_code: `EMP-${index}`,
    attendance_status: 'not_marked' as const,
    attendance_token: {
      token_hash: `${index.toString(16).padStart(64, '0')}`,
      token_version: 1,
      state: 'active' as const,
      token_expires_at: '2029-01-03T00:00:00.000Z',
      token_updated_at: '2028-12-31T23:59:00.000Z',
      evidence_observed_at: observedAt,
      evidence_valid_until: '2029-01-02T00:00:00.000Z',
    },
    room_number: null,
    meal_preference: null,
    has_alert: false,
  };
}

function installSession(): void {
  useSessionStore.getState().setSession({
    accessToken: 'access',
    accessTokenExpiresAt: '2030-01-01T01:00:00.000Z',
    refreshTokenExpiresAt: '2030-02-01T00:00:00.000Z',
    sessionId: 'coordinator-session',
    networkMode: 'online',
    principal: {
      id: PRINCIPAL_ID,
      accountId: PRINCIPAL_ID,
      principalType: 'coordinator',
      agencyId: AGENCY_ID,
      displayName: 'Coordinator',
      email: null,
      phoneNumber: null,
      forcePasswordChange: false,
    },
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  installSession();
});

afterEach(() => useSessionStore.getState().clear());

function sqliteAdapter(database: DatabaseSync) {
  return {
    getAllAsync: async (sql: string, ...parameters: unknown[]) => (
      database.prepare(sql).all(...(parameters as never[]))
    ),
    getFirstAsync: async (sql: string, ...parameters: unknown[]) => (
      database.prepare(sql).get(...(parameters as never[])) ?? null
    ),
    runAsync: async (sql: string, ...parameters: unknown[]) => {
      const bindings = parameters.length === 1 && Array.isArray(parameters[0])
        ? parameters[0]
        : parameters;
      const result = database.prepare(sql).run(...(bindings as never[]));
      return {
        changes: Number(result.changes),
        lastInsertRowId: Number(result.lastInsertRowid),
      };
    },
  };
}

function localRosterDatabase(options: Readonly<{
  boundary?: Readonly<{ last_display_name: string; last_passenger_id: string }>;
  complete?: boolean;
  rows?: readonly Readonly<{
    attendance_status: 'not_marked';
    display_name: string;
    employee_code: string | null;
    has_alert: number;
    id: string;
    meal_preference: string | null;
    room_number: string | null;
  }>[];
}> = {}) {
  const rows = options.rows ?? [];
  return {
    getAllAsync: jest.fn(async () => rows),
    getFirstAsync: jest.fn(async (sql: string) => {
      if (sql.includes('FROM local_roster_cursors')) return options.boundary ?? null;
      if (sql.includes('SELECT roster_version')) {
        return {
          advertised_roster_version: 7,
          roster_projection_complete: options.complete === false ? 0 : 1,
          roster_version: 7,
        };
      }
      if (sql.includes('COUNT(*) AS count')) return { count: rows.length };
      return null;
    }),
    runAsync: jest.fn(async () => ({ changes: 0, lastInsertRowId: 0 })),
  };
}

async function migratedRosterDatabase(): Promise<DatabaseSync> {
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
      roster_version INTEGER NOT NULL DEFAULT 0,
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
    VALUES ('${TRIP_ID}', '${AGENCY_ID}.${PRINCIPAL_ID}', 'coordinator', 7, 7);
    INSERT INTO coordinator_passengers(
      id, account_namespace, trip_id, display_name, attendance_status, updated_at
    ) VALUES (
      'old-passenger', '${AGENCY_ID}.${PRINCIPAL_ID}', '${TRIP_ID}',
      'Old Passenger', 'not_marked', '2030-01-01T00:00:00.000Z'
    );
    PRAGMA user_version = 17;
  `);
  await migrateAccountDatabase(
    { getFirstAsync: async (sql: string) => database.prepare(sql).get() } as never,
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
  return database;
}

test('stages and atomically promotes all 10,000 passengers with bounded SQLite writes', async () => {
  const all = Array.from({ length: MOBILE_GROUP_PASSENGER_CAPACITY }, (_, index) => passenger(index));
  mockedApiRequest.mockImplementation(async (path: string) => {
    const url = new URL(path, 'https://mobile.invalid');
    const offset = Number(url.searchParams.get('cursor') ?? 0);
    const items = all.slice(offset, offset + 100);
    return {
      items,
      next_cursor: offset + items.length < all.length ? String(offset + items.length) : null,
      total: all.length,
      roster_revision: 7,
    } as never;
  });

  const transaction = {
    getFirstAsync: jest.fn(async () => ({
      item_count: all.length,
      maximum_index: all.length - 1,
      minimum_index: 0,
    })),
    runAsync: jest.fn(async (sql: string, ...parameters: unknown[]) => {
      if (sql.includes('INSERT INTO coordinator_roster_staging')) {
        const bindings = parameters[0] as unknown[];
        return { changes: bindings.length / 19, lastInsertRowId: 1 };
      }
      if (sql.includes('INSERT INTO coordinator_passengers')) {
        return { changes: all.length, lastInsertRowId: 1 };
      }
      return { changes: 1, lastInsertRowId: 1 };
    }),
  };
  const database = { runAsync: jest.fn(async () => ({ changes: 1, lastInsertRowId: 1 })) };
  mockedOpenDatabase.mockResolvedValue(database as never);
  mockedWithTransaction.mockImplementation(async (_database, operation) => {
    await operation(transaction as never);
  });

  await expect(syncFullRoster(TRIP_ID)).resolves.toMatchObject({
    items: expect.any(Array),
    next_cursor: null,
    offline: false,
    total: MOBILE_GROUP_PASSENGER_CAPACITY,
  });

  expect(mockedApiRequest).toHaveBeenCalledTimes(100);
  const stagingCalls = transaction.runAsync.mock.calls.filter(([sql]) => (
    sql.includes('INSERT INTO coordinator_roster_staging')
  ));
  expect(stagingCalls).toHaveLength(Math.ceil(MOBILE_GROUP_PASSENGER_CAPACITY / 47));
  expect(Math.max(...stagingCalls.map(([, parameters]) => (parameters as unknown[]).length))).toBe(893);
  expect(transaction.runAsync.mock.calls.filter(([sql]) => (
    sql.includes('INSERT INTO coordinator_passengers') && sql.includes('SELECT id')
  ))).toHaveLength(1);
  expect(transaction.runAsync).toHaveBeenCalledWith(
    expect.stringContaining('UPDATE trips SET roster_projection_complete = 1'),
    `${AGENCY_ID}.${PRINCIPAL_ID}`,
    TRIP_ID,
  );
});

test('rolls the live roster marker back when final set-based promotion fails', async () => {
  const all = [passenger(0), passenger(1)];
  mockedApiRequest.mockResolvedValue({
    items: all,
    next_cursor: null,
    roster_revision: 7,
    total: all.length,
  } as never);
  const state = { live: 'old' };
  const transaction = {
    getFirstAsync: jest.fn(async () => ({
      item_count: all.length,
      maximum_index: all.length - 1,
      minimum_index: 0,
    })),
    runAsync: jest.fn(async (sql: string, ...parameters: unknown[]) => {
      if (sql.includes('INSERT INTO coordinator_roster_staging')) {
        const bindings = parameters[0] as unknown[];
        return { changes: bindings.length / 19, lastInsertRowId: 1 };
      }
      if (sql.includes('UPDATE coordinator_passengers SET roster_version = -1')) {
        state.live = 'marked-for-replacement';
      }
      if (sql.includes('INSERT INTO coordinator_passengers')) {
        throw new Error('promotion failed');
      }
      return { changes: 1, lastInsertRowId: 1 };
    }),
  };
  const database = { runAsync: jest.fn(async () => ({ changes: 1, lastInsertRowId: 1 })) };
  mockedOpenDatabase.mockResolvedValue(database as never);
  mockedWithTransaction.mockImplementation(async (_database, operation) => {
    const before = state.live;
    try {
      await operation(transaction as never);
    } catch (error) {
      state.live = before;
      throw error;
    }
  });

  await expect(syncFullRoster(TRIP_ID)).rejects.toThrow('promotion failed');
  expect(state.live).toBe('old');
  expect(database.runAsync).toHaveBeenCalledWith(
    expect.stringContaining('DELETE FROM coordinator_roster_staging'),
    `${AGENCY_ID}.${PRINCIPAL_ID}`,
    TRIP_ID,
    expect.any(String),
  );
});

test('does not reinterpret a remote keyset cursor as an offline cursor', async () => {
  const networkError = new Error('offline during remote pagination');
  mockedApiRequest.mockRejectedValue(networkError);

  await expect(loadRoster(TRIP_ID, '', 'remote-keyset-cursor')).rejects.toBe(networkError);

  expect(mockedApiRequest).toHaveBeenCalledTimes(1);
  expect(mockedOpenDatabase).not.toHaveBeenCalled();
});

test('returns an authoritative empty offline result when the complete projection has no match', async () => {
  mockedApiRequest.mockRejectedValue(new Error('offline'));
  mockedOpenDatabase.mockResolvedValue(localRosterDatabase() as never);

  await expect(loadRoster(TRIP_ID, 'Nobody')).resolves.toMatchObject({
    items: [],
    next_cursor: null,
    offline: true,
    projectionCompleteness: {
      fullReplacementCompleted: true,
      isComplete: true,
    },
    total: 0,
  });
});

test('keeps a local keyset traversal local instead of sending its cursor to the API', async () => {
  const row = {
    attendance_status: 'not_marked' as const,
    display_name: 'Passenger 001',
    employee_code: null,
    has_alert: 0,
    id: 'passenger-001',
    meal_preference: null,
    room_number: null,
  };
  mockedOpenDatabase.mockResolvedValue(localRosterDatabase({
    boundary: { last_display_name: 'Passenger 000', last_passenger_id: 'passenger-000' },
    rows: [row],
  }) as never);

  await expect(loadRoster(
    TRIP_ID,
    '',
    'local:v1:00000000-0000-4000-8000-000000000001',
  )).resolves.toMatchObject({ items: [{ ...row, has_alert: false }], offline: true });

  expect(mockedApiRequest).not.toHaveBeenCalled();
});

sqliteTest('executes the set-based replacement against SQLite and keeps FTS synchronized', async () => {
  const native = await migratedRosterDatabase();
  try {
    const adapter = sqliteAdapter(native);
    mockedOpenDatabase.mockResolvedValue(adapter as never);
    mockedWithTransaction.mockImplementation(async (_database, operation) => {
      native.exec('BEGIN IMMEDIATE');
      try {
        await operation(adapter as never);
        native.exec('COMMIT');
      } catch (error) {
        native.exec('ROLLBACK');
        throw error;
      }
    });
    mockedApiRequest.mockResolvedValue({
      items: [passenger(0), passenger(1)],
      next_cursor: null,
      total: 2,
      roster_revision: 7,
    } as never);

    await syncFullRoster(TRIP_ID);

    expect(native.prepare(
      'SELECT id FROM coordinator_passengers ORDER BY id',
    ).all().map((row) => row.id)).toEqual(['passenger-00000', 'passenger-00001']);
    expect(native.prepare(
      `SELECT passenger.id
         FROM coordinator_passengers_fts
         JOIN coordinator_passengers AS passenger
           ON passenger.rowid = coordinator_passengers_fts.rowid
        WHERE coordinator_passengers_fts MATCH '"passenger"*'
        ORDER BY passenger.id`,
    ).all().map((row) => row.id)).toEqual(['passenger-00000', 'passenger-00001']);
    expect(native.prepare(
      'SELECT roster_projection_complete FROM trips WHERE id = ?',
    ).get(TRIP_ID)).toMatchObject({ roster_projection_complete: 1 });
    expect(native.prepare(
      `SELECT attendance_token_hash, attendance_token_state
         FROM coordinator_passengers WHERE id = 'passenger-00000'`,
    ).get()).toMatchObject({
      attendance_token_hash: '0'.repeat(64),
      attendance_token_state: 'active',
    });
  } finally {
    native.close();
  }
});

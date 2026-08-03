import { apiRequest } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';

import { drainAttendanceQueue } from '../attendance-queue';

jest.mock('@/core/api/client', () => {
  const actual = jest.requireActual('@/core/api/client');
  return { ...actual, apiRequest: jest.fn() };
});
jest.mock('@/core/storage/database', () => ({
  openAccountDatabase: jest.fn(),
  withAccountTransaction: jest.fn(),
}));

const mockedApiRequest = jest.mocked(apiRequest);
const mockedOpenDatabase = jest.mocked(openAccountDatabase);
const mockedTransaction = jest.mocked(withAccountTransaction);

const TRIP_ID = '11111111-1111-4111-8111-111111111111';
const SESSION_ID = '22222222-2222-4222-8222-222222222222';
const ACCOUNT = 'agency-coordinator.coordinator-one';

const COORDINATOR_SESSION: MobileSession = {
  accessToken: 'access-token',
  accessTokenExpiresAt: '2030-01-01T00:00:00.000Z',
  refreshTokenExpiresAt: '2030-02-01T00:00:00.000Z',
  sessionId: '33333333-3333-4333-8333-333333333333',
  networkMode: 'online',
  principal: {
    id: 'coordinator-one',
    accountId: 'coordinator-one',
    principalType: 'coordinator',
    agencyId: 'agency-coordinator',
    displayName: 'Coordinator One',
    email: null,
    phoneNumber: null,
    forcePasswordChange: false,
  },
};

type QueueState = 'pending' | 'sending' | 'retryable' | 'rejected';

type QueueRow = {
  idempotency_key: string;
  account_namespace: string;
  trip_id: string;
  dedupe_key: string;
  payload_json: string;
  state: QueueState;
  attempt_count: number;
  next_attempt_at: string | null;
  last_error_code: string | null;
  created_at: string;
  updated_at: string;
};

type Receipt = {
  eventId: string;
  status: 'accepted' | 'already_applied';
};

function compactSql(sql: string): string {
  return sql.replace(/\s+/g, ' ').trim();
}

class FakeAttendanceDatabase {
  readonly rows: QueueRow[];
  readonly receipts = new Map<string, Receipt>();

  constructor(count: number) {
    this.rows = Array.from({ length: count }, (_, index) => queueRow(index + 1));
  }

  async getAllAsync<T>(sql: string, ...parameters: unknown[]): Promise<T[]> {
    const normalized = compactSql(sql);
    if (!normalized.includes('FROM pending_actions') || !normalized.includes('LIMIT 100')) {
      throw new Error(`Unexpected query: ${normalized}`);
    }
    const [account, tripId, now] = parameters as [string, string, string];
    return this.rows
      .filter((row) => (
        row.account_namespace === account
        && row.trip_id === tripId
        && (row.state === 'pending' || row.state === 'retryable')
        && (row.next_attempt_at === null || row.next_attempt_at <= now)
      ))
      .sort((left, right) => (
        left.created_at.localeCompare(right.created_at)
        || left.idempotency_key.localeCompare(right.idempotency_key)
      ))
      .slice(0, 100)
      .map((row) => ({
        idempotency_key: row.idempotency_key,
        dedupe_key: row.dedupe_key,
        payload_json: row.payload_json,
        attempt_count: row.attempt_count,
      })) as T[];
  }

  async runAsync(sql: string, ...parameters: unknown[]): Promise<{ changes: number }> {
    const normalized = compactSql(sql);
    if (normalized.includes("last_error_code = 'INTERRUPTED_RETRY'")) {
      const [updatedAt, account, tripId, staleBefore] = parameters as [
        string,
        string,
        string,
        string,
      ];
      let changes = 0;
      for (const row of this.rows) {
        if (
          row.account_namespace === account
          && row.trip_id === tripId
          && row.state === 'sending'
          && row.updated_at < staleBefore
        ) {
          row.state = 'retryable';
          row.next_attempt_at = null;
          row.last_error_code = 'INTERRUPTED_RETRY';
          row.updated_at = updatedAt;
          changes += 1;
        }
      }
      return { changes };
    }

    if (normalized.includes('attempt_count = attempt_count + 1')) {
      const [updatedAt, account, tripId, ...eventIds] = parameters as [
        string,
        string,
        string,
        ...string[],
      ];
      const eventIdSet = new Set(eventIds);
      let changes = 0;
      for (const row of this.rows) {
        if (
          row.account_namespace === account
          && row.trip_id === tripId
          && eventIdSet.has(row.idempotency_key)
          && (row.state === 'pending' || row.state === 'retryable')
        ) {
          row.state = 'sending';
          row.attempt_count += 1;
          row.next_attempt_at = null;
          row.last_error_code = null;
          row.updated_at = updatedAt;
          changes += 1;
        }
      }
      return { changes };
    }

    if (normalized.startsWith('INSERT OR IGNORE INTO attendance_scan_receipts')) {
      const [, , , , eventId, status] = parameters as [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ];
      this.receipts.set(eventId, {
        eventId,
        status: status as Receipt['status'],
      });
      return { changes: 1 };
    }

    if (normalized.startsWith('DELETE FROM pending_actions')) {
      const [eventId, account] = parameters as [string, string];
      const index = this.rows.findIndex((row) => (
        row.idempotency_key === eventId
        && row.account_namespace === account
        && row.state === 'sending'
      ));
      if (index < 0) return { changes: 0 };
      this.rows.splice(index, 1);
      return { changes: 1 };
    }

    if (normalized.includes("last_error_code = 'INVALID_LOCAL_PAYLOAD'")) {
      const [updatedAt, eventId, account] = parameters as [string, string, string];
      return this.updateRow(eventId, account, (row) => {
        row.state = 'rejected';
        row.next_attempt_at = null;
        row.last_error_code = 'INVALID_LOCAL_PAYLOAD';
        row.updated_at = updatedAt;
      });
    }

    if (normalized.includes("SET state = 'rejected'")) {
      const [errorCode, updatedAt, eventId, account] = parameters as [
        string,
        string,
        string,
        string,
      ];
      return this.updateRow(eventId, account, (row) => {
        row.state = 'rejected';
        row.next_attempt_at = null;
        row.last_error_code = errorCode;
        row.updated_at = updatedAt;
      });
    }

    if (normalized.includes("SET state = 'retryable'")) {
      const [nextAttemptAt, errorCode, updatedAt, eventId, account] = parameters as [
        string,
        string,
        string,
        string,
        string,
      ];
      return this.updateRow(eventId, account, (row) => {
        row.state = 'retryable';
        row.next_attempt_at = nextAttemptAt;
        row.last_error_code = errorCode;
        row.updated_at = updatedAt;
      });
    }

    if (normalized.includes('SET state = ?')) {
      const [state, nextAttemptAt, errorCode, updatedAt, eventId, account] = parameters as [
        QueueState,
        string | null,
        string,
        string,
        string,
        string,
      ];
      return this.updateRow(eventId, account, (row) => {
        row.state = state;
        row.next_attempt_at = nextAttemptAt;
        row.last_error_code = errorCode;
        row.updated_at = updatedAt;
      });
    }

    throw new Error(`Unexpected mutation: ${normalized}`);
  }

  private updateRow(
    eventId: string,
    account: string,
    update: (row: QueueRow) => void,
  ): { changes: number } {
    const row = this.rows.find((candidate) => (
      candidate.idempotency_key === eventId
      && candidate.account_namespace === account
      && candidate.state === 'sending'
    ));
    if (!row) return { changes: 0 };
    update(row);
    return { changes: 1 };
  }
}

function eventId(index: number): string {
  return `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`;
}

function signedQr(index: number): string {
  return `pdatt:${String(index).padStart(43, '0').slice(-43)}`;
}

function queueRow(index: number): QueueRow {
  const createdAt = new Date(Date.UTC(2029, 0, 1, 0, 0, 0, index)).toISOString();
  return {
    idempotency_key: eventId(index),
    account_namespace: ACCOUNT,
    trip_id: TRIP_ID,
    dedupe_key: `dedupe-${index}`,
    payload_json: JSON.stringify({
      session_id: SESSION_ID,
      signed_qr: signedQr(index),
      scanned_at: createdAt,
      source: 'qr',
    }),
    state: 'pending',
    attempt_count: 0,
    next_attempt_at: null,
    last_error_code: null,
    created_at: createdAt,
    updated_at: createdAt,
  };
}

function actionsFromRequest(options: unknown): { client_event_id: string }[] {
  return (options as { body: { actions: { client_event_id: string }[] } }).body.actions;
}

async function waitForRequest(): Promise<void> {
  for (let index = 0; index < 30; index += 1) {
    if (mockedApiRequest.mock.calls.length > 0) return;
    await Promise.resolve();
  }
  throw new Error('Attendance request was not started.');
}

beforeEach(() => {
  jest.clearAllMocks();
  useSessionStore.getState().setSession(COORDINATOR_SESSION);
  mockedTransaction.mockImplementation(async (database, task) => {
    await task(database);
  });
});

afterEach(() => {
  jest.useRealTimers();
  jest.restoreAllMocks();
  useSessionStore.getState().clear();
});

test('drains 1,500 scans in ordered API batches of at most 100', async () => {
  const database = new FakeAttendanceDatabase(1_500);
  const batches: string[][] = [];
  mockedOpenDatabase.mockResolvedValue(database as never);
  mockedApiRequest.mockImplementation(async (_path, options) => {
    const actions = actionsFromRequest(options);
    batches.push(actions.map((action) => action.client_event_id));
    return {
      results: actions.map((action) => ({
        client_event_id: action.client_event_id,
        status: 'accepted' as const,
        server_version: null,
        reason_code: null,
      })),
    };
  });

  await drainAttendanceQueue(TRIP_ID);

  expect(batches).toHaveLength(15);
  expect(batches.every((batch) => batch.length === 100)).toBe(true);
  expect(batches.flat()).toEqual(Array.from({ length: 1_500 }, (_, index) => eventId(index + 1)));
  expect(database.rows).toHaveLength(0);
  expect(database.receipts.size).toBe(1_500);
});

test('reconciles out-of-order accepted, already-applied and rejected results atomically by event id', async () => {
  const database = new FakeAttendanceDatabase(3);
  mockedOpenDatabase.mockResolvedValue(database as never);
  mockedApiRequest.mockImplementationOnce(async (_path, options) => {
    const actions = actionsFromRequest(options);
    const [first, second, third] = actions;
    if (!first || !second || !third) throw new Error('Expected three attendance actions.');
    return {
      results: [
        {
          client_event_id: second.client_event_id,
          status: 'already_applied' as const,
          server_version: null,
          reason_code: null,
        },
        {
          client_event_id: third.client_event_id,
          status: 'rejected' as const,
          server_version: null,
          reason_code: 'QR_REVOKED',
        },
        {
          client_event_id: first.client_event_id,
          status: 'accepted' as const,
          server_version: null,
          reason_code: null,
        },
      ],
    };
  });

  await drainAttendanceQueue(TRIP_ID);

  expect(database.receipts.get(eventId(1))?.status).toBe('accepted');
  expect(database.receipts.get(eventId(2))?.status).toBe('already_applied');
  expect(database.rows).toEqual([
    expect.objectContaining({
      idempotency_key: eventId(3),
      state: 'rejected',
      last_error_code: 'QR_REVOKED',
    }),
  ]);
  expect(mockedTransaction.mock.calls.length).toBeGreaterThanOrEqual(2);
});

test('preserves a transport-failed batch and retries it successfully later', async () => {
  jest.useFakeTimers({ now: new Date('2030-01-01T00:00:00.000Z') });
  jest.spyOn(Math, 'random').mockReturnValue(0);
  const database = new FakeAttendanceDatabase(120);
  mockedOpenDatabase.mockResolvedValue(database as never);
  mockedApiRequest.mockRejectedValueOnce(new Error('offline'));

  await drainAttendanceQueue(TRIP_ID);

  expect(database.rows).toHaveLength(120);
  expect(database.rows.filter((row) => row.state === 'retryable')).toHaveLength(100);
  expect(database.rows.filter((row) => row.state === 'pending')).toHaveLength(20);
  expect(database.rows.every((row) => row.state !== 'rejected')).toBe(true);

  jest.setSystemTime(new Date('2030-01-01T00:10:00.000Z'));
  mockedApiRequest.mockImplementation(async (_path, options) => {
    const actions = actionsFromRequest(options);
    return {
      results: actions.map((action) => ({
        client_event_id: action.client_event_id,
        status: 'accepted' as const,
        server_version: null,
        reason_code: null,
      })),
    };
  });

  await drainAttendanceQueue(TRIP_ID);

  expect(database.rows).toHaveLength(0);
  expect(database.receipts.size).toBe(120);
  expect(mockedApiRequest).toHaveBeenCalledTimes(3);
});

test('coalesces concurrent drains into one network batch', async () => {
  const database = new FakeAttendanceDatabase(80);
  mockedOpenDatabase.mockResolvedValue(database as never);
  let resolveRequest!: (value: unknown) => void;
  mockedApiRequest.mockImplementationOnce((_path, options) => {
    const actions = actionsFromRequest(options);
    return new Promise((resolve) => {
      resolveRequest = () => resolve({
        results: actions.map((action) => ({
          client_event_id: action.client_event_id,
          status: 'accepted' as const,
          server_version: null,
          reason_code: null,
        })),
      });
    }) as never;
  });

  const first = drainAttendanceQueue(TRIP_ID);
  const second = drainAttendanceQueue(TRIP_ID);
  const third = drainAttendanceQueue(TRIP_ID);
  expect(first).toBe(second);
  expect(second).toBe(third);
  await waitForRequest();
  expect(mockedApiRequest).toHaveBeenCalledTimes(1);

  resolveRequest(undefined);
  await Promise.all([first, second, third]);

  expect(mockedOpenDatabase).toHaveBeenCalledTimes(1);
  expect(mockedApiRequest).toHaveBeenCalledTimes(1);
  expect(database.rows).toHaveLength(0);
});

test('does not let a delayed retryable scan starve newer pending work', async () => {
  jest.useFakeTimers({ now: new Date('2030-01-01T00:00:00.000Z') });
  const database = new FakeAttendanceDatabase(2);
  const delayedRow = database.rows[0];
  if (!delayedRow) throw new Error('Expected a delayed attendance row.');
  delayedRow.state = 'retryable';
  delayedRow.next_attempt_at = '2030-01-01T01:00:00.000Z';
  mockedOpenDatabase.mockResolvedValue(database as never);
  mockedApiRequest.mockImplementationOnce(async (_path, options) => {
    const actions = actionsFromRequest(options);
    return {
      results: actions.map((action) => ({
        client_event_id: action.client_event_id,
        status: 'accepted' as const,
        server_version: null,
        reason_code: null,
      })),
    };
  });

  await drainAttendanceQueue(TRIP_ID);

  expect(database.rows).toEqual([
    expect.objectContaining({
      idempotency_key: eventId(1),
      state: 'retryable',
    }),
  ]);
  expect(database.receipts.has(eventId(2))).toBe(true);
});

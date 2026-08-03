import { ApiError, apiRequest } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';

import { drainNotificationReads } from '../notification-repository';

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
const NOTIFICATION_ID = '22222222-2222-4222-8222-222222222222';
const IDEMPOTENCY_KEY = '33333333-3333-4333-8333-333333333333';
const PASSENGER_SESSION: MobileSession = {
  accessToken: 'access-token',
  accessTokenExpiresAt: '2030-01-01T00:00:00.000Z',
  refreshTokenExpiresAt: '2030-02-01T00:00:00.000Z',
  sessionId: '44444444-4444-4444-8444-444444444444',
  networkMode: 'online',
  principal: {
    id: 'passenger-one',
    accountId: 'passenger-one',
    principalType: 'passenger',
    agencyId: 'agency-passenger',
    displayName: 'Passenger One',
    email: null,
    phoneNumber: null,
    forcePasswordChange: false,
  },
};

type QueueState = 'pending' | 'sending' | 'retryable' | 'rejected';

type QueueRow = {
  idempotency_key: string;
  dedupe_key: string;
  state: QueueState;
  attempt_count: number;
  next_attempt_at: string | null;
  last_error_code: string | null;
  created_at: string;
  updated_at: string;
};

function compactSql(sql: string): string {
  return sql.replace(/\s+/g, ' ').trim();
}

class FakeNotificationDatabase {
  readonly row: QueueRow;
  deleted = false;
  readAt: string | null = null;

  constructor(overrides: Partial<QueueRow> = {}) {
    this.row = {
      idempotency_key: IDEMPOTENCY_KEY,
      dedupe_key: NOTIFICATION_ID,
      state: 'pending',
      attempt_count: 0,
      next_attempt_at: null,
      last_error_code: null,
      created_at: '2029-01-01T00:00:00.000Z',
      updated_at: new Date().toISOString(),
      ...overrides,
    };
  }

  async getFirstAsync<T>(sql: string, ...parameters: unknown[]): Promise<T | null> {
    const normalized = compactSql(sql);
    if (!normalized.includes("action_type = 'notification.read'")) {
      throw new Error(`Unexpected query: ${normalized}`);
    }
    const [, , now] = parameters as [string, string, string];
    if (
      this.deleted
      || (this.row.state !== 'pending' && this.row.state !== 'retryable')
      || (this.row.next_attempt_at !== null && this.row.next_attempt_at > now)
    ) {
      return null;
    }
    return {
      idempotency_key: this.row.idempotency_key,
      dedupe_key: this.row.dedupe_key,
      attempt_count: this.row.attempt_count,
    } as T;
  }

  async runAsync(sql: string, ...parameters: unknown[]): Promise<{ changes: number }> {
    const normalized = compactSql(sql);
    if (normalized.includes("last_error_code = 'INTERRUPTED_RETRY'")) {
      const [updatedAt, , , staleBefore] = parameters as [string, string, string, string];
      if (!this.deleted && this.row.state === 'sending' && this.row.updated_at < staleBefore) {
        this.row.state = 'retryable';
        this.row.next_attempt_at = null;
        this.row.last_error_code = 'INTERRUPTED_RETRY';
        this.row.updated_at = updatedAt;
        return { changes: 1 };
      }
      return { changes: 0 };
    }
    if (normalized.includes('attempt_count = attempt_count + 1')) {
      const [updatedAt] = parameters as [string];
      if (this.deleted || (this.row.state !== 'pending' && this.row.state !== 'retryable')) {
        return { changes: 0 };
      }
      this.row.state = 'sending';
      this.row.attempt_count += 1;
      this.row.next_attempt_at = null;
      this.row.last_error_code = null;
      this.row.updated_at = updatedAt;
      return { changes: 1 };
    }
    if (normalized.startsWith('UPDATE mobile_notifications')) {
      this.readAt = parameters[0] as string;
      return { changes: 1 };
    }
    if (normalized.startsWith('DELETE FROM pending_actions')) {
      if (!this.deleted && this.row.state === 'sending') {
        this.deleted = true;
        return { changes: 1 };
      }
      return { changes: 0 };
    }
    if (normalized.includes("last_error_code = 'INVALID_NOTIFICATION_ID'")) {
      const [updatedAt] = parameters as [string];
      if (this.deleted || this.row.state !== 'sending') return { changes: 0 };
      this.row.state = 'rejected';
      this.row.next_attempt_at = null;
      this.row.last_error_code = 'INVALID_NOTIFICATION_ID';
      this.row.updated_at = updatedAt;
      return { changes: 1 };
    }
    if (normalized.includes('SET state = ?, next_attempt_at = ?, last_error_code = ?')) {
      const [state, nextAttemptAt, errorCode, updatedAt] = parameters as [
        QueueState,
        string | null,
        string,
        string,
      ];
      if (this.deleted || this.row.state !== 'sending') return { changes: 0 };
      this.row.state = state;
      this.row.next_attempt_at = nextAttemptAt;
      this.row.last_error_code = errorCode;
      this.row.updated_at = updatedAt;
      return { changes: 1 };
    }
    throw new Error(`Unexpected statement: ${normalized}`);
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

beforeEach(() => {
  jest.clearAllMocks();
  useSessionStore.setState({ session: PASSENGER_SESSION });
  mockedTransaction.mockImplementation(async (database, operation) => (
    operation(database as never)
  ));
});

afterEach(() => {
  useSessionStore.setState({ session: null });
});

test('coalesces concurrent drains and sends one claimed read action', async () => {
  const database = new FakeNotificationDatabase();
  mockedOpenDatabase.mockResolvedValue(database as never);
  const response = deferred<{ id: string; read_at: string }>();
  mockedApiRequest.mockReturnValue(response.promise);

  const first = drainNotificationReads(TRIP_ID);
  const second = drainNotificationReads(TRIP_ID);

  expect(second).toBe(first);
  response.resolve({ id: NOTIFICATION_ID, read_at: '2030-01-01T00:00:00.000Z' });
  await Promise.all([first, second]);

  expect(mockedApiRequest).toHaveBeenCalledTimes(1);
  expect(database.deleted).toBe(true);
  expect(database.readAt).toBe('2030-01-01T00:00:00.000Z');
});

test('backs off a transient failure and does not immediately claim it again', async () => {
  const database = new FakeNotificationDatabase();
  mockedOpenDatabase.mockResolvedValue(database as never);
  mockedApiRequest.mockRejectedValue(new Error('offline'));

  await drainNotificationReads(TRIP_ID);

  expect(database.row.state).toBe('retryable');
  expect(database.row.next_attempt_at).not.toBeNull();
  await drainNotificationReads(TRIP_ID);
  expect(mockedApiRequest).toHaveBeenCalledTimes(1);
});

test('recovers a stale process-death claim before draining', async () => {
  const database = new FakeNotificationDatabase({
    state: 'sending',
    updated_at: '2020-01-01T00:00:00.000Z',
  });
  mockedOpenDatabase.mockResolvedValue(database as never);
  mockedApiRequest.mockResolvedValue({
    id: NOTIFICATION_ID,
    read_at: '2030-01-01T00:00:00.000Z',
  });

  await drainNotificationReads(TRIP_ID);

  expect(mockedApiRequest).toHaveBeenCalledTimes(1);
  expect(database.deleted).toBe(true);
});

test('rejects malformed local identifiers without contacting the API', async () => {
  const database = new FakeNotificationDatabase({ dedupe_key: '../other-account' });
  mockedOpenDatabase.mockResolvedValue(database as never);

  await drainNotificationReads(TRIP_ID);

  expect(mockedApiRequest).not.toHaveBeenCalled();
  expect(database.row.state).toBe('rejected');
  expect(database.row.last_error_code).toBe('INVALID_NOTIFICATION_ID');
});

test('permanently rejects an authoritative non-retryable API response', async () => {
  const database = new FakeNotificationDatabase();
  mockedOpenDatabase.mockResolvedValue(database as never);
  mockedApiRequest.mockRejectedValue(
    new ApiError('Not permitted', 403, 'AUTHORIZATION_ERROR', null),
  );

  await drainNotificationReads(TRIP_ID);

  expect(database.row.state).toBe('rejected');
  expect(database.row.next_attempt_at).toBeNull();
  expect(database.row.last_error_code).toBe('AUTHORIZATION_ERROR');
});

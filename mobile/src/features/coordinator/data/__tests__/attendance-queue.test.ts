import { apiRequest, ApiError } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';
import {
  recordAttendanceAcknowledgement,
  recordAttendanceDeliveryBatchSize,
  recordAttendanceDeliveryFailure,
  recordAttendanceQueueToConfirmation,
  recordAttendanceRefreshRecovery,
  recordAttendanceRetryOutcome,
  recordAttendanceServerConfirmation,
  recordAttendanceTerminalRejection,
  recordExplicitAttendanceDiscard,
} from '@/core/observability/attendance-observability';
import { recordTripDurableQueueDepths } from '@/core/observability/queue-depth-observability';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';

import {
  acknowledgeAttendanceNeedsReview,
  acknowledgeRejectedAttendance,
  drainAttendanceQueue,
  listAttendanceNeedsReview,
  resetAttendanceQueueRuntimeForTests,
  retryAttendanceNeedsReview,
} from '../attendance-queue';
import { attendanceDeliveryFailureCategory } from '../attendance-queue-delivery';
import { refreshAttendanceSessions } from '../attendance-sessions';

jest.mock('@/core/api/client', () => {
  const actual = jest.requireActual('@/core/api/client');
  return { ...actual, apiRequest: jest.fn() };
});
jest.mock('@/core/storage/database', () => ({
  openAccountDatabase: jest.fn(),
  withAccountTransaction: jest.fn(),
}));
jest.mock('@/core/observability/attendance-observability', () => ({
  recordAttendanceAcknowledgement: jest.fn(),
  recordAttendanceDeliveryBatchSize: jest.fn(),
  recordAttendanceDeliveryFailure: jest.fn(),
  recordAttendanceLocalScanResult: jest.fn(),
  recordAttendanceQueueToConfirmation: jest.fn(),
  recordAttendanceRefreshRecovery: jest.fn(),
  recordAttendanceRetryOutcome: jest.fn(),
  recordAttendanceServerConfirmation: jest.fn(),
  recordAttendanceTerminalRejection: jest.fn(),
  recordExplicitAttendanceDiscard: jest.fn(),
}));
jest.mock('@/core/observability/queue-depth-observability', () => ({
  recordTripDurableQueueDepths: jest.fn(),
}));
jest.mock('../attendance-sessions', () => ({
  refreshAttendanceSessions: jest.fn(),
}));

const mockedApiRequest = jest.mocked(apiRequest);
const mockedOpenDatabase = jest.mocked(openAccountDatabase);
const mockedTransaction = jest.mocked(withAccountTransaction);
const mockedRecordExplicitAttendanceDiscard = jest.mocked(recordExplicitAttendanceDiscard);
const mockedRecordAttendanceAcknowledgement = jest.mocked(recordAttendanceAcknowledgement);
const mockedRecordAttendanceDeliveryBatchSize = jest.mocked(recordAttendanceDeliveryBatchSize);
const mockedRecordAttendanceDeliveryFailure = jest.mocked(recordAttendanceDeliveryFailure);
const mockedRecordAttendanceQueueToConfirmation = jest.mocked(
  recordAttendanceQueueToConfirmation,
);
const mockedRecordAttendanceRefreshRecovery = jest.mocked(recordAttendanceRefreshRecovery);
const mockedRecordAttendanceRetryOutcome = jest.mocked(recordAttendanceRetryOutcome);
const mockedRecordAttendanceServerConfirmation = jest.mocked(recordAttendanceServerConfirmation);
const mockedRecordAttendanceTerminalRejection = jest.mocked(recordAttendanceTerminalRejection);
const mockedRecordTripDurableQueueDepths = jest.mocked(recordTripDurableQueueDepths);
const mockedRefreshAttendanceSessions = jest.mocked(refreshAttendanceSessions);

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

type QueueState = 'pending' | 'sending' | 'retryable' | 'needs_review' | 'rejected';

type QueueRow = {
  idempotency_key: string;
  account_namespace: string;
  trip_id: string;
  dedupe_key: string;
  payload_json: string;
  state: QueueState;
  attempt_count: number;
  refresh_attempt_count: number;
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
    if (normalized.includes("state = 'needs_review'") && normalized.includes('payload_json')) {
      const [account, tripId] = parameters as [string, string];
      return this.rows
        .filter((row) => (
          row.account_namespace === account
          && row.trip_id === tripId
          && row.state === 'needs_review'
        ))
        .sort((left, right) => (
          right.updated_at.localeCompare(left.updated_at)
          || right.idempotency_key.localeCompare(left.idempotency_key)
        )) as T[];
    }
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
        created_at: row.created_at,
        refresh_attempt_count: row.refresh_attempt_count,
        last_error_code: row.last_error_code,
      })) as T[];
  }

  async getFirstAsync<T>(sql: string, ...parameters: unknown[]): Promise<T | null> {
    const normalized = compactSql(sql);
    if (!normalized.includes('MIN(next_attempt_at)')) {
      throw new Error(`Unexpected query: ${normalized}`);
    }
    const [account, tripId] = parameters as [string, string];
    const nextAttemptAt = this.rows
      .filter((row) => (
        row.account_namespace === account
        && row.trip_id === tripId
        && row.state === 'retryable'
        && row.next_attempt_at !== null
      ))
      .map((row) => row.next_attempt_at as string)
      .sort()[0] ?? null;
    return { next_attempt_at: nextAttemptAt } as T;
  }

  async runAsync(sql: string, ...parameters: unknown[]): Promise<{ changes: number }> {
    const normalized = compactSql(sql);
    if (
      normalized.includes("last_error_code = 'LOCAL_QUEUE_EXPIRED'")
      || normalized.includes("state IN ('needs_review', 'rejected') AND updated_at < ?")
      || normalized.includes('LIMIT -1 OFFSET 1000')
      || normalized.startsWith('DELETE FROM attendance_scan_receipts')
    ) {
      return { changes: 0 };
    }
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

    if (normalized.includes('SET refresh_attempt_count = 1, attempt_count = attempt_count + 1')) {
      const [updatedAt, eventId, account] = parameters as [string, string, string];
      return this.updateRow(eventId, account, (row) => {
        if (row.refresh_attempt_count !== 0) return;
        row.refresh_attempt_count = 1;
        row.attempt_count += 1;
        row.updated_at = updatedAt;
      });
    }

    if (
      normalized.includes('attempt_count = attempt_count + CASE')
      || normalized.includes('attempt_count = attempt_count + 1')
    ) {
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
          if (!row.last_error_code?.startsWith('REFRESH_PENDING:')) row.attempt_count += 1;
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
      if (normalized.includes("state = 'needs_review'")) {
        const [account, tripId, eventId] = parameters as [string, string, string];
        const index = this.rows.findIndex((row) => (
          row.account_namespace === account
          && row.trip_id === tripId
          && row.idempotency_key === eventId
          && row.state === 'needs_review'
        ));
        if (index < 0) return { changes: 0 };
        this.rows.splice(index, 1);
        return { changes: 1 };
      }
      if (
        normalized.includes("action_type = 'attendance.scan'")
        && normalized.includes("state = 'rejected'")
        && !normalized.includes('updated_at <')
        && !normalized.includes('idempotency_key IN')
      ) {
        const [account, tripId] = parameters as [string, string];
        const retained = this.rows.filter((row) => (
          row.account_namespace !== account
          || row.trip_id !== tripId
          || row.state !== 'rejected'
        ));
        const changes = this.rows.length - retained.length;
        this.rows.splice(0, this.rows.length, ...retained);
        return { changes };
      }
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

    if (normalized.includes("SET state = 'needs_review'")) {
      const [errorCode, updatedAt, eventId, account] = parameters as [
        string,
        string,
        string,
        string,
      ];
      return this.updateRow(eventId, account, (row) => {
        row.state = 'needs_review';
        if (normalized.includes('refresh_attempt_count = 1')) row.refresh_attempt_count = 1;
        row.next_attempt_at = null;
        row.last_error_code = errorCode;
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
      if (normalized.includes("last_error_code = 'MANUAL_REVIEW_RETRY'")) {
        const [updatedAt, account, tripId, eventId] = parameters as [
          string,
          string,
          string,
          string,
        ];
        const row = this.rows.find((candidate) => (
          candidate.idempotency_key === eventId
          && candidate.account_namespace === account
          && candidate.trip_id === tripId
          && candidate.state === 'needs_review'
        ));
        if (!row) return { changes: 0 };
        row.state = 'retryable';
        row.next_attempt_at = null;
        row.last_error_code = 'MANUAL_REVIEW_RETRY';
        row.updated_at = updatedAt;
        return { changes: 1 };
      }
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
  const createdAt = new Date(Date.UTC(2029, 11, 31, 23, 0, 0, index)).toISOString();
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
    refresh_attempt_count: 0,
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
  resetAttendanceQueueRuntimeForTests();
  useSessionStore.getState().setSession(COORDINATOR_SESSION);
  mockedRefreshAttendanceSessions.mockResolvedValue({
    items: [{
      id: SESSION_ID,
      name: 'Boarding',
      status: 'active',
      scanned_count: 0,
      assigned_count: 100,
      started_at: '2029-12-31T22:00:00.000Z',
      completed_at: null,
    }],
    selectedSessionId: SESSION_ID,
    offline: false,
  });
  mockedTransaction.mockImplementation(async (database, task) => {
    await task(database);
  });
});

afterEach(() => {
  resetAttendanceQueueRuntimeForTests();
  jest.useRealTimers();
  jest.restoreAllMocks();
  useSessionStore.getState().clear();
});

test.each([
  ['429', new ApiError('rate limited', 429, 'RATE_LIMITED', 30), 'rate_limited'],
  ['5xx', new ApiError('upstream unavailable', 503, 'UPSTREAM_FAILURE', null), 'server_error'],
  ['timeout', Object.assign(new Error('late'), { name: 'TimeoutError' }), 'timeout'],
  ['network', new TypeError('network unavailable'), 'network'],
  ['other', new Error('unexpected'), 'other'],
] as const)('classifies %s delivery failures without raw status/error labels', (_label, error, expected) => {
  expect(attendanceDeliveryFailureCategory(error)).toBe(expected);
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

  const result = await drainAttendanceQueue(TRIP_ID);

  expect(batches).toHaveLength(15);
  expect(batches.every((batch) => batch.length === 100)).toBe(true);
  expect(batches.flat()).toEqual(Array.from({ length: 1_500 }, (_, index) => eventId(index + 1)));
  expect(database.rows).toHaveLength(0);
  expect(database.receipts.size).toBe(1_500);
  expect(result).toEqual({
    settledBySession: { [SESSION_ID]: 1_500 },
    confirmedBySession: { [SESSION_ID]: 1_500 },
    newlyAcceptedBySession: { [SESSION_ID]: 1_500 },
    rejectedBySession: {},
  });
});

test('reconciles out-of-order accepted, already-applied and rejected results atomically by event id', async () => {
  jest.useFakeTimers({ now: new Date('2030-01-01T00:00:00.000Z') });
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

  const result = await drainAttendanceQueue(TRIP_ID);

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
  expect(result).toEqual({
    settledBySession: { [SESSION_ID]: 3 },
    confirmedBySession: { [SESSION_ID]: 2 },
    newlyAcceptedBySession: { [SESSION_ID]: 1 },
    rejectedBySession: { [SESSION_ID]: 1 },
  });
  expect(mockedRecordAttendanceDeliveryBatchSize).toHaveBeenCalledWith(3, 'success');
  expect(mockedRecordAttendanceServerConfirmation).toHaveBeenCalledWith('accepted', 1);
  expect(mockedRecordAttendanceServerConfirmation).toHaveBeenCalledWith('already_applied', 1);
  expect(mockedRecordAttendanceQueueToConfirmation).toHaveBeenCalledTimes(2);
  expect(mockedRecordAttendanceTerminalRejection).toHaveBeenCalledWith('QR_REVOKED', 1);
});

test('preserves a transport-failed batch and retries it successfully later', async () => {
  jest.useFakeTimers({ now: new Date('2030-01-01T00:00:00.000Z') });
  jest.spyOn(Math, 'random').mockReturnValue(0);
  const database = new FakeAttendanceDatabase(120);
  mockedOpenDatabase.mockResolvedValue(database as never);
  mockedApiRequest.mockRejectedValueOnce(new TypeError('Network request failed'));

  const offlineResult = await drainAttendanceQueue(TRIP_ID);

  expect(database.rows).toHaveLength(120);
  expect(database.rows.filter((row) => row.state === 'retryable')).toHaveLength(100);
  expect(database.rows.filter((row) => row.state === 'pending')).toHaveLength(20);
  expect(database.rows.every((row) => row.state !== 'rejected')).toBe(true);
  expect(offlineResult).toEqual({
    settledBySession: {},
    confirmedBySession: {},
    newlyAcceptedBySession: {},
    rejectedBySession: {},
  });

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

  const recoveredResult = await drainAttendanceQueue(TRIP_ID);

  expect(database.rows).toHaveLength(0);
  expect(database.receipts.size).toBe(120);
  expect(mockedApiRequest).toHaveBeenCalledTimes(3);
  expect(mockedRecordAttendanceAcknowledgement).toHaveBeenCalledTimes(3);
  expect(mockedRecordAttendanceAcknowledgement).toHaveBeenNthCalledWith(
    1,
    expect.any(Number),
    'offline',
  );
  expect(mockedRecordAttendanceDeliveryFailure).toHaveBeenCalledWith('network');
  expect(mockedRecordAttendanceRetryOutcome).toHaveBeenCalledWith(100, 'success');
  expect(mockedRecordTripDurableQueueDepths).toHaveBeenLastCalledWith(database, ACCOUNT, TRIP_ID);
  expect(recoveredResult).toEqual({
    settledBySession: { [SESSION_ID]: 120 },
    confirmedBySession: { [SESSION_ID]: 120 },
    newlyAcceptedBySession: { [SESSION_ID]: 120 },
    rejectedBySession: {},
  });
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
  const results = await Promise.all([first, second, third]);

  expect(mockedOpenDatabase).toHaveBeenCalledTimes(1);
  expect(mockedApiRequest).toHaveBeenCalledTimes(1);
  expect(database.rows).toHaveLength(0);
  expect(results).toEqual([
    {
      settledBySession: { [SESSION_ID]: 80 },
      confirmedBySession: { [SESSION_ID]: 80 },
      newlyAcceptedBySession: { [SESSION_ID]: 80 },
      rejectedBySession: {},
    },
    {
      settledBySession: { [SESSION_ID]: 80 },
      confirmedBySession: { [SESSION_ID]: 80 },
      newlyAcceptedBySession: { [SESSION_ID]: 80 },
      rejectedBySession: {},
    },
    {
      settledBySession: { [SESSION_ID]: 80 },
      confirmedBySession: { [SESSION_ID]: 80 },
      newlyAcceptedBySession: { [SESSION_ID]: 80 },
      rejectedBySession: {},
    },
  ]);
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

  const result = await drainAttendanceQueue(TRIP_ID);

  expect(database.rows).toEqual([
    expect.objectContaining({
      idempotency_key: eventId(1),
      state: 'retryable',
    }),
  ]);
  expect(database.receipts.has(eventId(2))).toBe(true);
  expect(result).toEqual({
    settledBySession: { [SESSION_ID]: 1 },
    confirmedBySession: { [SESSION_ID]: 1 },
    newlyAcceptedBySession: { [SESSION_ID]: 1 },
    rejectedBySession: {},
  });
});

test('authoritatively refreshes once and retries refresh_required with the same idempotency key', async () => {
  const database = new FakeAttendanceDatabase(1);
  const requestEventIds: string[] = [];
  mockedOpenDatabase.mockResolvedValue(database as never);
  mockedApiRequest
    .mockImplementationOnce(async (_path, options) => {
      const [action] = actionsFromRequest(options);
      if (!action) throw new Error('Expected one attendance action.');
      requestEventIds.push(action.client_event_id);
      return {
        results: [{
          client_event_id: action.client_event_id,
          status: 'refresh_required' as const,
          server_version: null,
          reason_code: 'ATTENDANCE_CONFLICT',
        }],
      };
    })
    .mockImplementationOnce(async (_path, options) => {
      const [action] = actionsFromRequest(options);
      if (!action) throw new Error('Expected one attendance action.');
      requestEventIds.push(action.client_event_id);
      return {
        results: [{
          client_event_id: action.client_event_id,
          status: 'accepted' as const,
          server_version: null,
          reason_code: null,
        }],
      };
    });

  await expect(drainAttendanceQueue(TRIP_ID)).resolves.toEqual({
    settledBySession: { [SESSION_ID]: 1 },
    confirmedBySession: { [SESSION_ID]: 1 },
    newlyAcceptedBySession: { [SESSION_ID]: 1 },
    rejectedBySession: {},
  });

  expect(mockedRefreshAttendanceSessions).toHaveBeenCalledTimes(1);
  expect(mockedRefreshAttendanceSessions).toHaveBeenCalledWith(TRIP_ID);
  expect(requestEventIds).toEqual([eventId(1), eventId(1)]);
  expect(database.rows).toHaveLength(0);
  expect(database.receipts.get(eventId(1))?.status).toBe('accepted');
  expect(mockedRecordAttendanceRefreshRecovery).toHaveBeenCalledWith(1, 'success');
});

test('persists an unavailable authoritative refresh and resumes it before another POST', async () => {
  jest.useFakeTimers({ now: new Date('2030-01-01T00:00:00.000Z') });
  jest.spyOn(Math, 'random').mockReturnValue(0);
  const database = new FakeAttendanceDatabase(1);
  const requestEventIds: string[] = [];
  mockedOpenDatabase.mockResolvedValue(database as never);
  mockedRefreshAttendanceSessions.mockResolvedValueOnce({
    items: [],
    selectedSessionId: null,
    offline: true,
  });
  mockedApiRequest
    .mockImplementationOnce(async (_path, options) => {
      const [action] = actionsFromRequest(options);
      if (!action) throw new Error('Expected one attendance action.');
      requestEventIds.push(action.client_event_id);
      return {
        results: [{
          client_event_id: action.client_event_id,
          status: 'refresh_required' as const,
          server_version: null,
          reason_code: 'ATTENDANCE_CONFLICT',
        }],
      };
    })
    .mockImplementationOnce(async (_path, options) => {
      const [action] = actionsFromRequest(options);
      if (!action) throw new Error('Expected one attendance action.');
      requestEventIds.push(action.client_event_id);
      return {
        results: [{
          client_event_id: action.client_event_id,
          status: 'accepted' as const,
          server_version: null,
          reason_code: null,
        }],
      };
    });

  await drainAttendanceQueue(TRIP_ID);

  expect(database.rows[0]).toMatchObject({
    state: 'retryable',
    attempt_count: 1,
    refresh_attempt_count: 0,
    last_error_code: 'REFRESH_PENDING:ATTENDANCE_CONFLICT',
    next_attempt_at: '2030-01-01T00:00:01.500Z',
  });
  expect(mockedApiRequest).toHaveBeenCalledTimes(1);
  expect(mockedRefreshAttendanceSessions).toHaveBeenCalledTimes(1);
  expect(mockedRecordAttendanceRefreshRecovery).toHaveBeenLastCalledWith(1, 'offline');

  jest.setSystemTime(new Date('2030-01-01T00:01:00.000Z'));
  await drainAttendanceQueue(TRIP_ID);

  expect(mockedRefreshAttendanceSessions).toHaveBeenCalledTimes(2);
  expect(requestEventIds).toEqual([eventId(1), eventId(1)]);
  expect(database.rows).toHaveLength(0);
  expect(database.receipts.get(eventId(1))?.status).toBe('accepted');
  expect(mockedRecordAttendanceRefreshRecovery).toHaveBeenLastCalledWith(1, 'success');
});

test('persists a second refresh_required as needs review and never loops the automatic refresh', async () => {
  const database = new FakeAttendanceDatabase(1);
  mockedOpenDatabase.mockResolvedValue(database as never);
  mockedApiRequest.mockImplementation(async (_path, options) => {
    const [action] = actionsFromRequest(options);
    if (!action) throw new Error('Expected one attendance action.');
    return {
      results: [{
        client_event_id: action.client_event_id,
        status: 'refresh_required' as const,
        server_version: null,
        reason_code: 'ATTENDANCE_CONFLICT',
      }],
    };
  });

  await expect(drainAttendanceQueue(TRIP_ID)).resolves.toEqual({
    settledBySession: { [SESSION_ID]: 1 },
    confirmedBySession: {},
    newlyAcceptedBySession: {},
    rejectedBySession: { [SESSION_ID]: 1 },
  });

  expect(mockedApiRequest).toHaveBeenCalledTimes(2);
  expect(mockedRefreshAttendanceSessions).toHaveBeenCalledTimes(1);
  expect(database.rows).toEqual([
    expect.objectContaining({
      idempotency_key: eventId(1),
      state: 'needs_review',
      refresh_attempt_count: 1,
      last_error_code: 'ATTENDANCE_CONFLICT',
    }),
  ]);
  await expect(listAttendanceNeedsReview(TRIP_ID)).resolves.toEqual([
    expect.objectContaining({
      idempotencyKey: eventId(1),
      sessionId: SESSION_ID,
      reasonCode: 'ATTENDANCE_CONFLICT',
      attemptCount: 2,
    }),
  ]);

  mockedApiRequest.mockClear();
  mockedRefreshAttendanceSessions.mockClear();
  await expect(drainAttendanceQueue(TRIP_ID)).resolves.toEqual({
    settledBySession: {},
    confirmedBySession: {},
    newlyAcceptedBySession: {},
    rejectedBySession: {},
  });
  expect(mockedApiRequest).not.toHaveBeenCalled();
  expect(mockedRefreshAttendanceSessions).not.toHaveBeenCalled();
});

test('manual needs-review retry preserves the refresh cap and can be acknowledged explicitly', async () => {
  const database = new FakeAttendanceDatabase(1);
  const row = database.rows[0];
  if (!row) throw new Error('Expected one attendance row.');
  row.state = 'needs_review';
  row.refresh_attempt_count = 1;
  row.last_error_code = 'ATTENDANCE_CONFLICT';
  mockedOpenDatabase.mockResolvedValue(database as never);
  mockedApiRequest.mockImplementationOnce(async (_path, options) => {
    const [action] = actionsFromRequest(options);
    if (!action) throw new Error('Expected one attendance action.');
    return {
      results: [{
        client_event_id: action.client_event_id,
        status: 'refresh_required' as const,
        server_version: null,
        reason_code: 'ATTENDANCE_CONFLICT',
      }],
    };
  });

  await expect(retryAttendanceNeedsReview(TRIP_ID, eventId(1))).resolves.toEqual({
    settledBySession: { [SESSION_ID]: 1 },
    confirmedBySession: {},
    newlyAcceptedBySession: {},
    rejectedBySession: { [SESSION_ID]: 1 },
  });
  expect(mockedApiRequest).toHaveBeenCalledTimes(1);
  expect(mockedRefreshAttendanceSessions).not.toHaveBeenCalled();
  expect(database.rows[0]).toMatchObject({
    idempotency_key: eventId(1),
    state: 'needs_review',
    refresh_attempt_count: 1,
  });

  await expect(acknowledgeAttendanceNeedsReview(TRIP_ID, eventId(1))).resolves.toBe(true);
  expect(mockedRecordExplicitAttendanceDiscard).toHaveBeenCalledWith(1);
  await expect(listAttendanceNeedsReview(TRIP_ID)).resolves.toEqual([]);
});

test('records only a count when rejected attendance is explicitly discarded', async () => {
  const database = new FakeAttendanceDatabase(2);
  for (const row of database.rows) row.state = 'rejected';
  mockedOpenDatabase.mockResolvedValue(database as never);

  await expect(acknowledgeRejectedAttendance(TRIP_ID)).resolves.toBe(2);

  expect(database.rows).toEqual([]);
  expect(mockedRecordExplicitAttendanceDiscard).toHaveBeenCalledWith(2);
});

test('honors Retry-After and wakes the queue at the exact earliest eligible instant', async () => {
  jest.useFakeTimers({ now: new Date('2030-01-01T00:00:00.000Z') });
  const database = new FakeAttendanceDatabase(1);
  mockedOpenDatabase.mockResolvedValue(database as never);
  mockedApiRequest.mockRejectedValueOnce(
    new ApiError('Slow down.', 429, 'RATE_LIMITED', 37),
  );

  await drainAttendanceQueue(TRIP_ID);

  expect(database.rows[0]).toMatchObject({
    state: 'retryable',
    next_attempt_at: '2030-01-01T00:00:37.000Z',
    last_error_code: 'RATE_LIMITED',
  });
  expect(mockedRecordAttendanceDeliveryFailure).toHaveBeenCalledWith('rate_limited');
  expect(mockedApiRequest).toHaveBeenCalledTimes(1);
  mockedApiRequest.mockImplementationOnce(async (_path, options) => {
    const [action] = actionsFromRequest(options);
    if (!action) throw new Error('Expected one attendance action.');
    return {
      results: [{
        client_event_id: action.client_event_id,
        status: 'accepted' as const,
        server_version: null,
        reason_code: null,
      }],
    };
  });

  await jest.advanceTimersByTimeAsync(36_999);
  expect(mockedApiRequest).toHaveBeenCalledTimes(1);
  expect(database.rows).toHaveLength(1);

  await jest.advanceTimersByTimeAsync(1);
  expect(mockedApiRequest).toHaveBeenCalledTimes(2);
  expect(database.rows).toHaveLength(0);
  expect(database.receipts.get(eventId(1))?.status).toBe('accepted');
});

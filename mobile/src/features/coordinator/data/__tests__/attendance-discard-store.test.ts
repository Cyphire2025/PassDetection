import { apiRequest, ApiError } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';
import { getInstallationId } from '@/core/storage/secure-store';

import {
  attendanceDiscardAuditStatus,
  discardAttendanceScanIssue,
  drainAttendanceDiscardTombstones,
} from '../attendance-discard-store';

jest.mock('expo-crypto', () => ({
  randomUUID: jest.fn(() => '77777777-7777-4777-8777-777777777777'),
}));
jest.mock('@/core/api/client', () => {
  const actual = jest.requireActual('@/core/api/client') as object;
  return { ...actual, apiRequest: jest.fn() };
});
jest.mock('@/core/storage/database', () => ({
  openAccountDatabase: jest.fn(),
  withAccountTransaction: jest.fn(),
}));
jest.mock('@/core/storage/secure-store', () => ({
  getInstallationId: jest.fn(async () => '88888888-8888-4888-8888-888888888888'),
}));

const mockedApiRequest = jest.mocked(apiRequest);
const mockedOpenAccountDatabase = jest.mocked(openAccountDatabase);
const mockedWithAccountTransaction = jest.mocked(withAccountTransaction);
const mockedGetInstallationId = jest.mocked(getInstallationId);

const ACCOUNT = '66666666-6666-4666-8666-666666666666.55555555-5555-4555-8555-555555555555';
const TRIP = '11111111-1111-4111-8111-111111111111';
const SESSION = '22222222-2222-4222-8222-222222222222';
const IDEMPOTENCY = '99999999-9999-4999-8999-999999999999';
const SCAN_REFERENCE = 'a'.repeat(64);

type SourceRow = Readonly<{
  captured_at: string;
  idempotency_key: string;
  passenger_id: string;
  scan_reference: string;
  session_id: string;
  state: string;
  trip_id: string;
}>;

type Tombstone = {
  account_namespace: string;
  attempt_count: number;
  captured_at: string | null;
  discard_event_id: string;
  discarded_at: string;
  installation_runtime_id: string;
  last_error_code: string | null;
  next_attempt_at: string | null;
  reason_category: string;
  scan_reference: string;
  session_id: string;
  source_idempotency_key: string;
  state: 'pending' | 'sending' | 'retryable' | 'rejected' | 'synchronized';
  synchronized_at: string | null;
  trip_id: string;
  updated_at: string;
};

class FakeDatabase {
  readonly sources: SourceRow[] = [{
    captured_at: '2026-08-23T10:00:00.000Z',
    idempotency_key: IDEMPOTENCY,
    passenger_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    scan_reference: SCAN_REFERENCE,
    session_id: SESSION,
    state: 'rejected',
    trip_id: TRIP,
  }];

  readonly tombstones: Tombstone[] = [];

  getFirstAsync = jest.fn(async (sql: string, ...parameters: unknown[]) => {
    if (sql.includes('WHERE source_idempotency_key = ?')) {
      const row = this.tombstones.find(
        (candidate) => candidate.source_idempotency_key === parameters[0],
      );
      return row ?? null;
    }
    if (sql.includes('SELECT trip_id, session_id')) {
      const account = parameters[0];
      const trip = parameters[2];
      return this.tombstones.find((row) => (
        row.account_namespace === account
        && (trip === null || row.trip_id === trip)
        && ['pending', 'retryable'].includes(row.state)
        && (row.next_attempt_at === null || row.next_attempt_at <= String(parameters[1]))
      )) ?? null;
    }
    return null;
  });

  getAllAsync = jest.fn(async (sql: string, ...parameters: unknown[]) => {
    if (sql.includes('FROM pending_actions action')) {
      const [account, trip, , idempotency] = parameters;
      return this.sources.filter((row) => (
        account === ACCOUNT
        && (trip === null || row.trip_id === trip)
        && (idempotency === null || row.idempotency_key === idempotency)
      ));
    }
    if (sql.includes('COUNT(*) AS count')) {
      const [account, trip, , session] = parameters;
      const counts = new Map<string, number>();
      for (const row of this.tombstones) {
        if (
          row.account_namespace !== account
          || (trip !== null && row.trip_id !== trip)
          || (session !== null && row.session_id !== session)
        ) continue;
        counts.set(row.state, (counts.get(row.state) ?? 0) + 1);
      }
      return [...counts].map(([state, count]) => ({ state, count }));
    }
    if (sql.includes('FROM attendance_discard_tombstones')) {
      const [account, trip, session, now] = parameters;
      return this.tombstones.filter((row) => (
        row.account_namespace === account
        && row.trip_id === trip
        && row.session_id === session
        && ['pending', 'retryable'].includes(row.state)
        && (row.next_attempt_at === null || row.next_attempt_at <= String(now))
      ));
    }
    return [];
  });

  runAsync = jest.fn(async (sql: string, ...parameters: unknown[]) => {
    if (sql.includes('INSERT OR IGNORE INTO attendance_discard_tombstones')) {
      if (this.tombstones.some((row) => row.source_idempotency_key === parameters[1])) {
        return { changes: 0, lastInsertRowId: 0 };
      }
      this.tombstones.push({
        account_namespace: String(parameters[2]),
        attempt_count: 0,
        captured_at: parameters[9] === null ? null : String(parameters[9]),
        discard_event_id: String(parameters[0]),
        discarded_at: String(parameters[10]),
        installation_runtime_id: String(parameters[6]),
        last_error_code: null,
        next_attempt_at: String(parameters[11]),
        reason_category: String(parameters[8]),
        scan_reference: String(parameters[7]),
        session_id: String(parameters[4]),
        source_idempotency_key: String(parameters[1]),
        state: 'pending',
        synchronized_at: null,
        trip_id: String(parameters[3]),
        updated_at: String(parameters[13]),
      });
      return { changes: 1, lastInsertRowId: 1 };
    }
    if (sql.includes('DELETE FROM pending_actions')) {
      const idempotency = parameters[2];
      const index = this.sources.findIndex((row) => row.idempotency_key === idempotency);
      if (index >= 0) this.sources.splice(index, 1);
      return { changes: index >= 0 ? 1 : 0, lastInsertRowId: 0 };
    }
    const eventId = String(parameters.at(-1));
    const row = this.tombstones.find((candidate) => candidate.discard_event_id === eventId);
    if (sql.includes("SET state = 'sending'")) {
      const sendingRow = this.tombstones.find(
        (candidate) => candidate.discard_event_id === parameters[3],
      );
      if (sendingRow) sendingRow.state = 'sending';
    } else if (sql.includes("SET state = 'synchronized'")) {
      const synchronizedRow = this.tombstones.find(
        (candidate) => candidate.discard_event_id === parameters[3],
      );
      if (synchronizedRow) {
        synchronizedRow.state = 'synchronized';
        synchronizedRow.synchronized_at = String(parameters[0]);
      }
    } else if (sql.includes("SET state = 'rejected'")) {
      const rejectedRow = this.tombstones.find(
        (candidate) => candidate.discard_event_id === parameters[3],
      );
      if (rejectedRow) {
        rejectedRow.state = 'rejected';
        rejectedRow.last_error_code = String(parameters[0]);
      }
    } else if (sql.includes('SET state = ?, attempt_count = ?') && row) {
      row.state = String(parameters[0]) as Tombstone['state'];
      row.attempt_count = Number(parameters[1]);
      row.next_attempt_at = parameters[2] === null ? null : String(parameters[2]);
      row.last_error_code = String(parameters[3]);
    }
    return { changes: row ? 1 : 0, lastInsertRowId: 0 };
  });
}

function coordinatorSession(accountId = '55555555-5555-4555-8555-555555555555'): MobileSession {
  return {
    accessToken: 'access-token',
    accessTokenExpiresAt: '2030-01-01T00:00:00.000Z',
    refreshTokenExpiresAt: '2030-01-02T00:00:00.000Z',
    sessionId: '33333333-3333-4333-8333-333333333333',
    networkMode: 'online',
    principal: {
      id: '44444444-4444-4444-8444-444444444444',
      accountId,
      agencyId: '66666666-6666-4666-8666-666666666666',
      principalType: 'coordinator',
      displayName: 'Coordinator',
      email: null,
      phoneNumber: null,
      forcePasswordChange: false,
    },
  };
}

let database: FakeDatabase;

beforeEach(() => {
  jest.clearAllMocks();
  database = new FakeDatabase();
  mockedOpenAccountDatabase.mockResolvedValue(database as never);
  mockedWithAccountTransaction.mockImplementation(async (_database, task) => {
    await task(database as never);
  });
  mockedGetInstallationId.mockResolvedValue('88888888-8888-4888-8888-888888888888');
  useSessionStore.setState({ status: 'authenticated', session: coordinatorSession() });
});

afterEach(() => {
  useSessionStore.setState({ status: 'anonymous', session: null });
});

test('persists a privacy-safe tombstone before deleting the local scan and is idempotent', async () => {
  await expect(Promise.all([
    discardAttendanceScanIssue(TRIP, IDEMPOTENCY),
    discardAttendanceScanIssue(TRIP, IDEMPOTENCY),
  ])).resolves.toEqual(expect.arrayContaining([true, false]));

  expect(database.sources).toHaveLength(0);
  expect(database.tombstones).toHaveLength(1);
  expect(database.tombstones[0]).toMatchObject({
    account_namespace: ACCOUNT,
    installation_runtime_id: '88888888-8888-4888-8888-888888888888',
    reason_category: 'operator_discard',
    scan_reference: SCAN_REFERENCE,
    state: 'pending',
  });
  expect(JSON.stringify(database.tombstones)).not.toContain('pdatt:');
  const statements = database.runAsync.mock.calls.map(([sql]) => String(sql));
  expect(statements.findIndex((sql) => sql.includes('INSERT OR IGNORE'))).toBeLessThan(
    statements.findIndex((sql) => sql.includes('DELETE FROM pending_actions')),
  );
});

test('survives a recoverable delivery failure and eventually synchronizes exactly once', async () => {
  await discardAttendanceScanIssue(TRIP, IDEMPOTENCY);
  mockedApiRequest.mockRejectedValueOnce(
    new ApiError('Unavailable', 503, 'SCANNER_UNAVAILABLE', 1),
  );

  await expect(drainAttendanceDiscardTombstones(TRIP)).resolves.toMatchObject({ pending: 1 });
  expect(database.tombstones[0]).toMatchObject({
    attempt_count: 1,
    last_error_code: 'SCANNER_UNAVAILABLE',
    state: 'retryable',
  });

  database.tombstones[0]!.next_attempt_at = null;
  const receivedAt = new Date().toISOString();
  mockedApiRequest.mockResolvedValueOnce({
    items: [{
      discard_event_id: '77777777-7777-4777-8777-777777777777',
      received_at: receivedAt,
      reason_code: null,
      status: 'accepted',
    }],
  });
  await expect(drainAttendanceDiscardTombstones(TRIP)).resolves.toMatchObject({
    pending: 0,
    synchronized: 1,
  });
  expect(mockedApiRequest).toHaveBeenCalledTimes(2);
  expect(mockedApiRequest.mock.calls[1]?.[1].body).toEqual({
    items: [{
      captured_at: '2026-08-23T10:00:00.000Z',
      discard_event_id: '77777777-7777-4777-8777-777777777777',
      discarded_at: expect.any(String),
      reason_category: 'operator_discard',
      scan_reference: SCAN_REFERENCE,
    }],
  });
});

test('keeps server-rejected evidence terminal and scopes status to the active account', async () => {
  await discardAttendanceScanIssue(TRIP, IDEMPOTENCY);
  mockedApiRequest.mockResolvedValueOnce({
    items: [{
      discard_event_id: '77777777-7777-4777-8777-777777777777',
      received_at: null,
      reason_code: 'SESSION_CLOSED',
      status: 'rejected',
    }],
  });

  await expect(drainAttendanceDiscardTombstones(TRIP)).resolves.toMatchObject({ rejected: 1 });
  expect(database.tombstones[0]).toMatchObject({
    last_error_code: 'SESSION_CLOSED',
    state: 'rejected',
  });
  useSessionStore.setState({
    status: 'authenticated',
    session: coordinatorSession('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'),
  });
  await expect(attendanceDiscardAuditStatus(TRIP)).resolves.toEqual({
    pending: 0,
    rejected: 0,
    synchronized: 0,
  });
});

import { apiRequest } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';
import { captureSyncContext, SyncContextChangedError } from '@/core/sync/sync-context';

import type {
  AttendanceSession,
  MissingPassenger,
} from '../../api/coordinator-contracts';
import {
  createAttendanceSession,
  leaveAttendanceSession,
  loadAttendanceSessionDetail,
  refreshAttendanceSessions,
  replaceAttendanceSessionsInTransaction,
  replaceMissingAttendanceInTransaction,
} from '../attendance-sessions';

jest.mock('@/core/api/client', () => ({ apiRequest: jest.fn() }));
jest.mock('@/core/storage/database', () => ({
  openAccountDatabase: jest.fn(),
  withAccountTransaction: jest.fn(),
}));

const mockedApiRequest = jest.mocked(apiRequest);
const mockedOpenDatabase = jest.mocked(openAccountDatabase);
const mockedTransaction = jest.mocked(withAccountTransaction);

const TRIP_ID = '11111111-1111-4111-8111-111111111111';
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

function attendanceSession(index: number): AttendanceSession {
  return {
    id: `session-${index}`,
    name: `Session ${index}`,
    status: index === 0 ? 'active' : 'completed',
    scanned_count: index,
    assigned_count: 10_000,
    started_at: '2030-01-01T00:00:00.000Z',
    completed_at: index === 0 ? null : '2030-01-01T01:00:00.000Z',
  };
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
  useSessionStore.setState({ session: COORDINATOR_SESSION });
  mockedTransaction.mockImplementation(async (database, operation) => operation(database as never));
});

afterEach(() => {
  useSessionStore.setState({ session: null });
});

test('coordinator activity creation fails locally before any server or database write', async () => {
  await expect(createAttendanceSession(TRIP_ID, 'Unauthorized count')).rejects.toThrow(
    'Only a Client Manager can create an attendance activity',
  );

  expect(mockedApiRequest).not.toHaveBeenCalled();
  expect(mockedOpenDatabase).not.toHaveBeenCalled();
});

test('writes 10k attendance sessions with bounded staging and O(batch) upserts', async () => {
  const transaction = {
    runAsync: jest.fn(async (_sql: string, ..._parameters: unknown[]) => ({
      changes: 1,
      lastInsertRowId: 0,
    })),
  };

  await replaceAttendanceSessionsInTransaction(transaction as never, {
    account: ACCOUNT,
    tripId: TRIP_ID,
    sessions: Array.from({ length: 10_000 }, (_, index) => attendanceSession(index)),
    updatedAt: '2030-01-01T02:00:00.000Z',
  });

  expect(transaction.runAsync).toHaveBeenCalledTimes(
    2 + Math.ceil(10_000 / 900) + Math.ceil(10_000 / 90) + 2,
  );
  expect(transaction.runAsync.mock.calls.every((call) => call.slice(1).length <= 900)).toBe(true);
  expect(transaction.runAsync.mock.calls.at(-2)?.[0]).toContain('NOT EXISTS');
});

test('finishing coordinator scanning only clears the device-local selection', async () => {
  const database = {
    runAsync: jest.fn(async (_sql: string, ..._parameters: unknown[]) => ({
      changes: 1,
      lastInsertRowId: 0,
    })),
  };
  mockedOpenDatabase.mockResolvedValue(database as never);

  await leaveAttendanceSession(TRIP_ID, 'session-one');

  expect(mockedApiRequest).not.toHaveBeenCalled();
  expect(database.runAsync).toHaveBeenCalledTimes(1);
  expect(database.runAsync.mock.calls[0]?.[0]).toContain('DELETE FROM attendance_session_selection');
  expect(database.runAsync.mock.calls[0]?.slice(1)).toEqual([
    ACCOUNT,
    TRIP_ID,
    'session-one',
  ]);
});

test('writes 10k missing attendees with one scoped delete and bounded inserts', async () => {
  const transaction = {
    runAsync: jest.fn(async (_sql: string, ..._parameters: unknown[]) => ({
      changes: 1,
      lastInsertRowId: 0,
    })),
  };
  const missing = Array.from({ length: 10_000 }, (_, index): MissingPassenger => ({
    id: `passenger-${index}`,
    display_name: `Passenger ${index}`,
  }));

  await replaceMissingAttendanceInTransaction(transaction as never, {
    account: ACCOUNT,
    tripId: TRIP_ID,
    sessionId: 'session-one',
    missing,
    updatedAt: '2030-01-01T02:00:00.000Z',
  });

  expect(transaction.runAsync).toHaveBeenCalledTimes(1 + Math.ceil(10_000 / 150));
  expect(transaction.runAsync.mock.calls.every((call) => call.slice(1).length <= 900)).toBe(true);
});

test('does not promote or sweep an authoritative session set after a failed write batch', async () => {
  const transaction = {
    runAsync: jest.fn(async (sql: string, ..._parameters: unknown[]) => {
      if (sql.includes('INSERT INTO attendance_sessions')) throw new Error('disk full');
      return { changes: 1, lastInsertRowId: 0 };
    }),
  };

  await expect(replaceAttendanceSessionsInTransaction(transaction as never, {
    account: ACCOUNT,
    tripId: TRIP_ID,
    sessions: [attendanceSession(0)],
    updatedAt: '2030-01-01T02:00:00.000Z',
  })).rejects.toThrow('disk full');

  expect(transaction.runAsync.mock.calls.some(([sql]) => (
    String(sql).startsWith('DELETE FROM attendance_sessions')
  ))).toBe(false);
});

test('publishes page one but keeps the prior complete local snapshot after page two fails', async () => {
  const cached = attendanceSession(99);
  const fresh = attendanceSession(0);
  const database = {
    getAllAsync: jest.fn(async () => [cached]),
    getFirstAsync: jest.fn(async () => null),
  };
  mockedOpenDatabase.mockResolvedValue(database as never);
  mockedApiRequest
    .mockResolvedValueOnce({ items: [fresh], next_cursor: 'next' })
    .mockRejectedValueOnce(new Error('offline on page two'));
  const onPage = jest.fn();

  await expect(refreshAttendanceSessions(TRIP_ID, undefined, onPage)).resolves.toEqual({
    items: [cached],
    selectedSessionId: null,
    offline: true,
  });

  expect(onPage).toHaveBeenCalledTimes(1);
  expect(onPage).toHaveBeenCalledWith([fresh]);
  expect(mockedTransaction).not.toHaveBeenCalled();
});

test('publishes missing attendees page by page and replaces local rows only after completion', async () => {
  const session = attendanceSession(0);
  const firstMissing: MissingPassenger = { id: 'passenger-one', display_name: 'Passenger One' };
  const secondMissing: MissingPassenger = { id: 'passenger-two', display_name: 'Passenger Two' };
  const secondPage = deferred<{
    session: AttendanceSession;
    missing: MissingPassenger[];
    next_cursor: null;
  }>();
  const database = {
    runAsync: jest.fn(async (_sql: string, ..._parameters: unknown[]) => ({
      changes: 1,
      lastInsertRowId: 0,
    })),
  };
  mockedOpenDatabase.mockResolvedValue(database as never);
  mockedApiRequest
    .mockResolvedValueOnce({ session, missing: [firstMissing], next_cursor: 'next' })
    .mockReturnValueOnce(secondPage.promise as never);
  const onPage = jest.fn();

  const result = loadAttendanceSessionDetail(TRIP_ID, session.id, undefined, onPage);
  await Promise.resolve();
  await Promise.resolve();

  expect(onPage).toHaveBeenCalledWith({ session, missing: [firstMissing] });
  expect(mockedTransaction).not.toHaveBeenCalled();

  secondPage.resolve({ session, missing: [secondMissing], next_cursor: null });
  await expect(result).resolves.toEqual({
    session,
    missing: [firstMissing, secondMissing],
    offline: false,
  });
  expect(onPage).toHaveBeenLastCalledWith({
    session,
    missing: [firstMissing, secondMissing],
  });
  expect(mockedTransaction).toHaveBeenCalledTimes(1);
});

test('cancels pagination before page two and before replacement when the account switches', async () => {
  mockedApiRequest.mockResolvedValue({
    items: [attendanceSession(0)],
    next_cursor: 'next',
  });
  const lease = captureSyncContext();

  try {
    await expect(refreshAttendanceSessions(TRIP_ID, lease.context, () => {
      useSessionStore.setState({ session: null });
    })).rejects.toBeInstanceOf(SyncContextChangedError);
  } finally {
    lease.release();
  }

  expect(mockedApiRequest).toHaveBeenCalledTimes(1);
  expect(mockedOpenDatabase).not.toHaveBeenCalled();
  expect(mockedTransaction).not.toHaveBeenCalled();
});

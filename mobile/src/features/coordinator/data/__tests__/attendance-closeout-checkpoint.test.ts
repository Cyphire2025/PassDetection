import { apiRequest } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';
import { openAccountDatabase } from '@/core/storage/database';
import { waitFor } from '@testing-library/react-native';

import {
  collectAttendanceCloseoutCheckpoint,
  publishAttendanceCloseoutCheckpoint,
} from '../attendance-closeout-checkpoint';

jest.mock('@/core/api/client', () => ({ apiRequest: jest.fn() }));
jest.mock('@/core/storage/database', () => ({ openAccountDatabase: jest.fn() }));

const mockedApiRequest = jest.mocked(apiRequest);
const mockedOpenAccountDatabase = jest.mocked(openAccountDatabase);
const tripId = '11111111-1111-4111-8111-111111111111';

function coordinatorSession(suffix: string): MobileSession {
  return {
    accessToken: `access-token-${suffix}`,
    accessTokenExpiresAt: '2030-01-01T01:00:00.000Z',
    refreshTokenExpiresAt: '2030-01-02T00:00:00.000Z',
    sessionId: `33333333-3333-4333-8333-${suffix.padStart(12, '0')}`,
    networkMode: 'online',
    principal: {
      id: `44444444-4444-4444-8444-${suffix.padStart(12, '0')}`,
      accountId: `55555555-5555-4555-8555-${suffix.padStart(12, '0')}`,
      agencyId: '66666666-6666-4666-8666-666666666666',
      principalType: 'coordinator',
      displayName: 'Coordinator',
      email: 'coordinator@example.test',
      phoneNumber: null,
      forcePasswordChange: false,
    },
  };
}

function serverResponse(overrides: Record<string, unknown> = {}) {
  return {
    pending_count: 0,
    sending_count: 0,
    retryable_count: 0,
    needs_review_count: 0,
    unreviewed_rejected_count: 0,
    oldest_pending_age_seconds: null,
    reported_at: '2030-01-01T00:00:00.000Z',
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  useSessionStore.setState({ status: 'authenticated', session: coordinatorSession('1') });
});

afterEach(() => {
  useSessionStore.setState({ status: 'anonymous', session: null });
});

test('maps every unresolved state and conservatively applies trip-level rejected rows', async () => {
  const getAllAsync = jest.fn().mockResolvedValue([
    { state: 'pending', count: 2, oldest_created_at: '2030-01-01T00:00:00.000Z' },
    { state: 'sending', count: 1, oldest_created_at: '2030-01-01T00:00:05.000Z' },
    { state: 'retryable', count: 3, oldest_created_at: '2030-01-01T00:00:10.000Z' },
    { state: 'needs_review', count: 4, oldest_created_at: null },
    { state: 'rejected', count: 5, oldest_created_at: null },
  ]);
  const getFirstAsync = jest.fn().mockResolvedValue({ count: 0 });
  mockedOpenAccountDatabase.mockResolvedValue({ getAllAsync, getFirstAsync } as never);

  const result = await collectAttendanceCloseoutCheckpoint(
    tripId,
    '22222222-2222-4222-8222-222222222222',
    Date.parse('2030-01-01T00:01:00.000Z'),
  );

  expect(result).toEqual({
    pending_count: 2,
    sending_count: 1,
    retryable_count: 3,
    needs_review_count: 4,
    unreviewed_rejected_count: 5,
    oldest_pending_age_seconds: 60,
  });
  expect(getAllAsync.mock.calls[0]?.[0]).toContain("state = 'rejected'");
  expect(getAllAsync.mock.calls[0]?.[0]).toContain("json_extract(payload_json, '$.session_id')");
  expect(getAllAsync.mock.calls[0]?.slice(1)).toEqual([
    '66666666-6666-4666-8666-666666666666.55555555-5555-4555-8555-000000000001',
    tripId,
    '22222222-2222-4222-8222-222222222222',
  ]);
});

test('invalid oldest timestamps fail closed with the conservative maximum age', async () => {
  mockedOpenAccountDatabase.mockResolvedValue({
    getAllAsync: jest.fn().mockResolvedValue([
      { state: 'pending', count: 1, oldest_created_at: 'not-a-time' },
    ]),
    getFirstAsync: jest.fn().mockResolvedValue({ count: 0 }),
  } as never);

  await expect(collectAttendanceCloseoutCheckpoint(
    tripId,
    '22222222-2222-4222-8222-222222222223',
  )).resolves.toMatchObject({
    pending_count: 1,
    oldest_pending_age_seconds: 31_536_000,
  });
});

test('account switch after queue read prevents any checkpoint request', async () => {
  const firstSession = coordinatorSession('1');
  useSessionStore.setState({ status: 'authenticated', session: firstSession });
  mockedOpenAccountDatabase.mockResolvedValue({
    getAllAsync: jest.fn(async () => {
      useSessionStore.setState({ status: 'authenticated', session: coordinatorSession('2') });
      return [];
    }),
    getFirstAsync: jest.fn().mockResolvedValue({ count: 0 }),
  } as never);

  await expect(publishAttendanceCloseoutCheckpoint(
    tripId,
    '22222222-2222-4222-8222-222222222224',
  )).rejects.toThrow('account changed');
  expect(mockedApiRequest).not.toHaveBeenCalled();
});

test('manual and interval triggers serialize, coalesce, and recompute one final report', async () => {
  const sessionId = '22222222-2222-4222-8222-222222222225';
  const getAllAsync = jest.fn().mockResolvedValue([]);
  const getFirstAsync = jest.fn().mockResolvedValue({ count: 0 });
  mockedOpenAccountDatabase.mockResolvedValue({ getAllAsync, getFirstAsync } as never);
  let resolveFirst!: (value: ReturnType<typeof serverResponse>) => void;
  const firstResponse = new Promise<ReturnType<typeof serverResponse>>((resolve) => {
    resolveFirst = resolve;
  });
  mockedApiRequest
    .mockReturnValueOnce(firstResponse)
    .mockResolvedValueOnce(serverResponse());

  const first = publishAttendanceCloseoutCheckpoint(tripId, sessionId);
  const second = publishAttendanceCloseoutCheckpoint(tripId, sessionId);
  const third = publishAttendanceCloseoutCheckpoint(tripId, sessionId);
  await waitFor(() => expect(mockedApiRequest).toHaveBeenCalledTimes(1));

  resolveFirst(serverResponse());
  await expect(first).resolves.toMatchObject({ reported_at: expect.any(String) });
  await expect(Promise.all([second, third])).resolves.toHaveLength(2);

  expect(mockedApiRequest).toHaveBeenCalledTimes(2);
  expect(getAllAsync).toHaveBeenCalledTimes(2);
  const body = mockedApiRequest.mock.calls[1]?.[1].body as Record<string, unknown>;
  expect(Object.keys(body).sort()).toEqual([
    'needs_review_count',
    'oldest_pending_age_seconds',
    'pending_count',
    'retryable_count',
    'sending_count',
    'unreviewed_rejected_count',
  ]);
});

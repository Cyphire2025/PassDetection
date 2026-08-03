import { ApiError, apiRequest } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import { openAccountDatabase } from '@/core/storage/database';

import { applyCoordinatorPassengerChanges } from '../coordinator-repository';

jest.mock('@/core/api/client', () => {
  const actual = jest.requireActual('@/core/api/client');
  return { ...actual, apiRequest: jest.fn() };
});
jest.mock('@/core/storage/database', () => ({
  openAccountDatabase: jest.fn(),
  withAccountTransaction: jest.fn(),
}));

const TRIP_ID = '11111111-1111-4111-8111-111111111111';
const PASSENGER_ID = '22222222-2222-4222-8222-222222222222';
const AGENCY_ID = '33333333-3333-4333-8333-333333333333';
const ACCOUNT_ID = '44444444-4444-4444-8444-444444444444';

const mockedApiRequest = jest.mocked(apiRequest);
const mockedOpenDatabase = jest.mocked(openAccountDatabase);

beforeEach(() => {
  jest.clearAllMocks();
  useSessionStore.getState().setSession({
    accessToken: 'access',
    accessTokenExpiresAt: '2030-01-01T01:00:00.000Z',
    refreshTokenExpiresAt: '2030-02-01T00:00:00.000Z',
    sessionId: 'coordinator-session',
    networkMode: 'online',
    principal: {
      id: ACCOUNT_ID,
      accountId: ACCOUNT_ID,
      principalType: 'coordinator',
      agencyId: AGENCY_ID,
      displayName: 'Coordinator',
      email: null,
      phoneNumber: null,
      forcePasswordChange: false,
    },
  });
});

afterEach(() => useSessionStore.getState().clear());

test('treats a scoped 404 after an upsert event as an authoritative tombstone', async () => {
  const database = {
    runAsync: jest.fn(async () => ({ changes: 1, lastInsertRowId: 0 })),
  };
  mockedOpenDatabase.mockResolvedValue(database as never);
  mockedApiRequest.mockRejectedValue(
    new ApiError('Passenger is no longer in the roster.', 404, 'NOT_FOUND', null),
  );

  await applyCoordinatorPassengerChanges(TRIP_ID, [
    { passengerId: PASSENGER_ID, operation: 'upsert' },
  ]);

  expect(database.runAsync).toHaveBeenCalledWith(
    expect.stringContaining('DELETE FROM coordinator_passengers'),
    `${AGENCY_ID}.${ACCOUNT_ID}`,
    TRIP_ID,
    PASSENGER_ID,
  );
});

test('does not turn a transient passenger fetch failure into a local deletion', async () => {
  const database = {
    runAsync: jest.fn(async () => ({ changes: 1, lastInsertRowId: 0 })),
  };
  mockedOpenDatabase.mockResolvedValue(database as never);
  mockedApiRequest.mockRejectedValue(
    new ApiError('Temporary failure.', 503, 'UNAVAILABLE', null),
  );

  await expect(
    applyCoordinatorPassengerChanges(TRIP_ID, [
      { passengerId: PASSENGER_ID, operation: 'upsert' },
    ]),
  ).rejects.toMatchObject({ status: 503 });
  expect(database.runAsync).not.toHaveBeenCalled();
});

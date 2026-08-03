import { ApiError, apiRequest } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';

import { refreshItinerary } from '../itinerary-repository';

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

const TEST_SESSION: MobileSession = {
  accessToken: 'access-token',
  accessTokenExpiresAt: '2030-01-01T00:00:00.000Z',
  refreshTokenExpiresAt: '2030-02-01T00:00:00.000Z',
  sessionId: 'session-id',
  networkMode: 'online',
  principal: {
    id: 'passenger-id',
    accountId: 'passenger-id',
    principalType: 'passenger',
    agencyId: 'agency-id',
    displayName: 'Passenger',
    email: null,
    phoneNumber: null,
    forcePasswordChange: false,
  },
};

const TRIP_ID = '11111111-1111-4111-8111-111111111111';

describe('itinerary cache authority', () => {
  afterEach(() => {
    jest.clearAllMocks();
    useSessionStore.getState().clear();
  });

  it('atomically removes cached itinerary rows when the server reports no published itinerary', async () => {
    const transaction = { runAsync: jest.fn().mockResolvedValue({ changes: 1 }) };
    const database = {};
    mockedOpenDatabase.mockResolvedValue(database as never);
    mockedTransaction.mockImplementation(async (received, task) => {
      expect(received).toBe(database);
      await task(transaction as never);
    });
    mockedApiRequest.mockRejectedValue(
      new ApiError('Published mobile itinerary was not found.', 404, 'NOT_FOUND', null),
    );

    useSessionStore.getState().setSession(TEST_SESSION);
    await expect(refreshItinerary(TRIP_ID)).resolves.toEqual({ itinerary: null, offline: false });

    expect(mockedTransaction).toHaveBeenCalledTimes(1);
    expect(transaction.runAsync).toHaveBeenNthCalledWith(
      1,
      'DELETE FROM itinerary_items WHERE account_namespace = ? AND trip_id = ?',
      'agency-id.passenger-id',
      TRIP_ID,
    );
    expect(transaction.runAsync).toHaveBeenNthCalledWith(
      2,
      'DELETE FROM itinerary_days WHERE account_namespace = ? AND trip_id = ?',
      'agency-id.passenger-id',
      TRIP_ID,
    );
  });

  it('keeps the cached itinerary available for a transient network failure', async () => {
    const database = {
      getAllAsync: jest
        .fn()
        .mockResolvedValueOnce([{
          id: 'day-1',
          version: 3,
          day_number: 1,
          calendar_date: '2030-01-05',
          title: 'Arrival',
          sort_order: 1,
        }])
        .mockResolvedValueOnce([{
          id: 'item-1',
          day_id: 'day-1',
          title: 'Airport reporting',
          description: null,
          starts_at: null,
          ends_at: null,
          location_name: null,
          latitude: null,
          longitude: null,
          sort_order: 1,
        }]),
    };
    mockedOpenDatabase.mockResolvedValue(database as never);
    mockedApiRequest.mockRejectedValue(new TypeError('Network request failed'));

    useSessionStore.getState().setSession(TEST_SESSION);
    const result = await refreshItinerary(TRIP_ID);

    expect(result.offline).toBe(true);
    expect(result.itinerary?.version).toBe(3);
    expect(result.itinerary?.days[0]?.items[0]?.title).toBe('Airport reporting');
    expect(mockedTransaction).not.toHaveBeenCalled();
  });
});

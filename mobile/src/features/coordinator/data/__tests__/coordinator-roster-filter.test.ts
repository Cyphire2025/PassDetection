import { apiRequest } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';

import { loadRoster } from '../coordinator-repository';
import { queryLocalRoster } from '../local-roster-search';

jest.mock('@/core/api/client', () => {
  const actual = jest.requireActual('@/core/api/client');
  return { ...actual, apiRequest: jest.fn() };
});
jest.mock('@/core/storage/database', () => ({
  openAccountDatabase: jest.fn(),
  withAccountTransaction: jest.fn(),
}));
jest.mock('../local-roster-search', () => {
  const actual = jest.requireActual('../local-roster-search');
  return { ...actual, queryLocalRoster: jest.fn() };
});

const TRIP_ID = '11111111-1111-4111-8111-111111111111';
const AGENCY_ID = '22222222-2222-4222-8222-222222222222';
const ACCOUNT_ID = '33333333-3333-4333-8333-333333333333';

const mockedApiRequest = jest.mocked(apiRequest);
const mockedOpenDatabase = jest.mocked(openAccountDatabase);
const mockedTransaction = jest.mocked(withAccountTransaction);
const mockedQueryLocalRoster = jest.mocked(queryLocalRoster);

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
  mockedOpenDatabase.mockResolvedValue({} as never);
  mockedTransaction.mockResolvedValue(undefined as never);
});

afterEach(() => useSessionStore.getState().clear());

test('sends the rooming filter as part of the authoritative remote cursor query', async () => {
  mockedApiRequest.mockResolvedValue({ items: [], next_cursor: null, total: 0 });

  await expect(loadRoster(TRIP_ID, '', null, undefined, 'rooming')).resolves.toMatchObject({
    items: [],
    offline: false,
    total: 0,
  });

  expect(mockedApiRequest).toHaveBeenCalledWith(
    `/mobile/coordinator/groups/${TRIP_ID}/passengers?filter=rooming&limit=100`,
    expect.objectContaining({ schema: expect.anything() }),
  );
});

test('preserves the meals filter when the first remote page falls back to SQLite', async () => {
  mockedApiRequest.mockRejectedValue(new TypeError('Network request failed'));
  mockedQueryLocalRoster.mockResolvedValue({
    items: [],
    next_cursor: null,
    offline: true,
    projectionCompleteness: {
      advertisedRosterVersion: 7,
      appliedRosterVersion: 7,
      fullReplacementCompleted: true,
      isComplete: true,
    },
    total: 0,
  });

  await expect(loadRoster(TRIP_ID, '', null, undefined, 'meals')).resolves.toMatchObject({
    offline: true,
  });

  expect(mockedQueryLocalRoster).toHaveBeenCalledWith(expect.objectContaining({
    accountNamespace: `${AGENCY_ID}.${ACCOUNT_ID}`,
    filter: 'meals',
    tripId: TRIP_ID,
  }));
});

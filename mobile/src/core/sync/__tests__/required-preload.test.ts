import type { MobileSession } from '@/core/auth/types';

import { preloadAuthenticatedWorkspace } from '../required-preload';

const SESSION: MobileSession = {
  accessToken: 'access-token',
  accessTokenExpiresAt: '2026-08-03T22:00:00.000Z',
  refreshTokenExpiresAt: '2026-09-02T21:00:00.000Z',
  sessionId: '33333333-3333-4333-8333-333333333333',
  networkMode: 'online',
  principal: {
    id: '22222222-2222-4222-8222-222222222222',
    accountId: '22222222-2222-4222-8222-222222222222',
    principalType: 'passenger',
    agencyId: '11111111-1111-4111-8111-111111111111',
    displayName: 'Passenger One',
    email: null,
    phoneNumber: '+919876543210',
    forcePasswordChange: false,
  },
};

const mockPreloadPassengerTrip = jest.fn();
const mockRefreshTrips = jest.fn();

jest.mock('@/core/auth/session-store', () => ({
  useSessionStore: {
    getState: () => ({ session: SESSION }),
  },
}));
jest.mock('@/features/content/data/passenger-preload', () => ({
  preloadPassengerTrip: (...args: unknown[]) => mockPreloadPassengerTrip(...args),
}));
jest.mock('@/features/content/data/manager-preload', () => ({
  preloadManagerTrips: jest.fn(),
}));
jest.mock('@/features/coordinator/data/coordinator-preload', () => ({
  preloadCoordinatorTrips: jest.fn(),
}));
jest.mock('@/features/trips/data/trip-repository', () => ({
  refreshTrips: (...args: unknown[]) => mockRefreshTrips(...args),
}));

beforeEach(() => {
  jest.clearAllMocks();
  mockPreloadPassengerTrip.mockResolvedValue({
    tripId: '44444444-4444-4444-8444-444444444444',
    failedDownloads: 0,
    selectionRequired: false,
  });
});

test('uses the already committed login principal and starts passenger preparation directly', async () => {
  const progress = jest.fn();

  await expect(preloadAuthenticatedWorkspace(progress)).resolves.toEqual({
    destination: '/(passenger)/(tabs)/trip',
  });

  expect(progress).toHaveBeenNthCalledWith(1, {
    percent: 4,
    message: 'Preparing your workspace',
    completedLabel: 'Secure session ready',
  });
  expect(mockPreloadPassengerTrip).toHaveBeenCalledTimes(1);
  expect(mockRefreshTrips).not.toHaveBeenCalled();
});

import * as BackgroundTask from 'expo-background-task';
import * as TaskManager from 'expo-task-manager';

import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';

import { BACKGROUND_SYNC_TASK } from '../background-sync';
import { syncAllTrips } from '../sync-service';

const mockBootstrapSession = jest.fn(async () => undefined);
const mockRetryPendingTripPurges = jest.fn(async () => undefined);
const mockPurgeExpiredTripCaches = jest.fn(async () => [] as string[]);

jest.mock('expo-background-task', () => ({
  BackgroundTaskResult: { Success: 1, Failed: 2 },
  registerTaskAsync: jest.fn(async () => undefined),
  unregisterTaskAsync: jest.fn(async () => undefined),
}));

jest.mock('expo-task-manager', () => ({
  isTaskDefined: jest.fn(() => false),
  defineTask: jest.fn(),
  isAvailableAsync: jest.fn(async () => true),
  isTaskRegisteredAsync: jest.fn(async () => false),
}));

jest.mock('@/core/auth/session-service', () => ({
  bootstrapSession: () => mockBootstrapSession(),
}));

jest.mock('../access-cache', () => ({
  retryPendingTripPurges: () => mockRetryPendingTripPurges(),
  purgeExpiredTripCaches: () => mockPurgeExpiredTripCaches(),
}));

jest.mock('../sync-service', () => ({
  syncAllTrips: jest.fn(),
}));

const mockedSyncAllTrips = jest.mocked(syncAllTrips);

const session: MobileSession = {
  accessToken: 'access-token',
  accessTokenExpiresAt: '2030-01-01T01:00:00.000Z',
  refreshTokenExpiresAt: '2030-02-01T00:00:00.000Z',
  sessionId: 'session-passenger',
  networkMode: 'online',
  principal: {
    id: 'principal-a',
    accountId: 'account-a',
    principalType: 'passenger',
    agencyId: 'agency-a',
    displayName: 'Passenger',
    email: null,
    phoneNumber: null,
    forcePasswordChange: false,
  },
};

function registeredTask(): () => Promise<number> {
  const registration = jest.mocked(TaskManager.defineTask).mock.calls.find(
    ([taskName]) => taskName === BACKGROUND_SYNC_TASK,
  );
  if (!registration) throw new Error('Background task was not registered.');
  return registration[1] as unknown as () => Promise<number>;
}

beforeEach(() => {
  mockedSyncAllTrips.mockReset();
  mockBootstrapSession.mockClear();
  mockRetryPendingTripPurges.mockClear();
  mockPurgeExpiredTripCaches.mockClear();
  useSessionStore.getState().setSession(session);
});

test('the OS task reports failure when every assigned trip fails', async () => {
  mockedSyncAllTrips.mockResolvedValue({
    results: [],
    failures: [
      { tripId: 'trip-a', category: 'network', retryable: true, code: 'SYNC_NETWORK' },
      { tripId: 'trip-b', category: 'server', retryable: true, code: 'SYNC_SERVER' },
    ],
    requestedTripCount: 2,
    tripsChanged: false,
    removedTripIds: [],
  });

  await expect(registeredTask()()).resolves.toBe(BackgroundTask.BackgroundTaskResult.Failed);
});

test('the OS task reports failure for an observable partial sync', async () => {
  mockedSyncAllTrips.mockResolvedValue({
    results: [{
      tripId: 'trip-a',
      cursor: 2,
      changes: 1,
      changed: true,
      syncedAt: '2030-01-01T00:00:00.000Z',
      documentPrefetch: null,
    }],
    failures: [
      { tripId: 'trip-b', category: 'network', retryable: true, code: 'SYNC_NETWORK' },
    ],
    requestedTripCount: 2,
    tripsChanged: false,
    removedTripIds: [],
  });

  await expect(registeredTask()()).resolves.toBe(BackgroundTask.BackgroundTaskResult.Failed);
});

test('an empty assignment is a successful background no-op', async () => {
  mockedSyncAllTrips.mockResolvedValue({
    results: [],
    failures: [],
    requestedTripCount: 0,
    tripsChanged: false,
    removedTripIds: [],
  });

  await expect(registeredTask()()).resolves.toBe(BackgroundTask.BackgroundTaskResult.Success);
});

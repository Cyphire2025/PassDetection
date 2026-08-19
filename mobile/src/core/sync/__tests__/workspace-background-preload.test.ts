import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';
import { DEFAULT_TRIP_TIME_ZONE } from '@/core/localization/time-zone';
import type { ImmutableSyncContext } from '@/core/sync/sync-context';
import type { Trip } from '@/features/trips/model/trip';

import {
  scheduleRemainingWorkspacePreparation,
  WORKSPACE_BACKGROUND_PRELOAD_CONCURRENCY,
} from '../workspace-background-preload';

const mockPreloadManagerTrip = jest.fn();
const mockPreloadCoordinatorTrip = jest.fn();

jest.mock('@/features/content/data/manager-preload', () => ({
  preloadManagerTrip: (...args: unknown[]) => mockPreloadManagerTrip(...args),
}));
jest.mock('@/features/coordinator/data/coordinator-preload', () => ({
  preloadCoordinatorTrip: (...args: unknown[]) => mockPreloadCoordinatorTrip(...args),
}));

const MANAGER_SESSION: MobileSession = {
  accessToken: 'manager-access-token',
  accessTokenExpiresAt: '2026-08-03T22:00:00.000Z',
  refreshTokenExpiresAt: '2026-09-02T21:00:00.000Z',
  sessionId: '33333333-3333-4333-8333-333333333333',
  networkMode: 'online',
  principal: {
    id: '22222222-2222-4222-8222-222222222222',
    accountId: '22222222-2222-4222-8222-222222222222',
    principalType: 'client_manager',
    agencyId: '11111111-1111-4111-8111-111111111111',
    displayName: 'Manager One',
    email: 'manager@example.com',
    phoneNumber: null,
    forcePasswordChange: false,
  },
};

const OTHER_MANAGER_SESSION: MobileSession = {
  ...MANAGER_SESSION,
  accessToken: 'other-manager-access-token',
  sessionId: '77777777-7777-4777-8777-777777777777',
  principal: {
    ...MANAGER_SESSION.principal,
    id: '66666666-6666-4666-8666-666666666666',
    accountId: '66666666-6666-4666-8666-666666666666',
    displayName: 'Manager Two',
    email: 'manager-two@example.com',
  },
};

function trip(index: number): Trip {
  const suffix = String(index).padStart(12, '0');
  return {
    id: `44444444-4444-4444-8444-${suffix}`,
    name: `Trip ${index}`,
    destination: 'Singapore',
    travelDate: '2026-09-01',
    returnDate: '2026-09-05',
    timeZone: DEFAULT_TRIP_TIME_ZONE,
    role: 'client_manager',
    accessGeneration: 1,
    accessExpiresAt: null,
    itineraryVersion: 1,
    commonDocumentVersion: 1,
    announcementVersion: 1,
    updatedAt: '2026-08-03T00:00:00.000Z',
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  useSessionStore.getState().setSession(MANAGER_SESSION);
});

afterEach(() => {
  useSessionStore.getState().clear();
});

test('processes 500 remaining trips with fixed bounded concurrency', async () => {
  const trips = Array.from({ length: 500 }, (_, index) => trip(index));
  let active = 0;
  let maximumActive = 0;
  mockPreloadManagerTrip.mockImplementation(async () => {
    active += 1;
    maximumActive = Math.max(maximumActive, active);
    await Promise.resolve();
    active -= 1;
    return { failedDownloads: 0 };
  });

  await expect(scheduleRemainingWorkspacePreparation('client_manager', trips)).resolves.toEqual({
    attemptedTrips: 500,
    failedTrips: 0,
  });

  expect(mockPreloadManagerTrip).toHaveBeenCalledTimes(500);
  expect(maximumActive).toBe(WORKSPACE_BACKGROUND_PRELOAD_CONCURRENCY);
  expect(maximumActive).toBe(2);
  const contexts = new Set(
    mockPreloadManagerTrip.mock.calls.map((call) => call[2] as ImmutableSyncContext),
  );
  expect(contexts.size).toBe(1);
});

test('isolates a later-trip failure and continues the remaining account lane', async () => {
  const trips = Array.from({ length: 12 }, (_, index) => trip(index));
  mockPreloadManagerTrip.mockImplementation(async (current: Trip) => {
    if (current.id === trips[5]!.id) throw new Error('trip-local preparation failure');
    return { failedDownloads: 0 };
  });

  await expect(scheduleRemainingWorkspacePreparation('client_manager', trips)).resolves.toEqual({
    attemptedTrips: 12,
    failedTrips: 1,
  });

  expect(mockPreloadManagerTrip).toHaveBeenCalledTimes(12);
});

test('aborts the old-account lane on account switch before another trip can start', async () => {
  const trips = Array.from({ length: 500 }, (_, index) => trip(index));
  mockPreloadManagerTrip.mockImplementation((
    _trip: Trip,
    _onProgress: unknown,
    syncContext: ImmutableSyncContext,
  ) => new Promise((_resolve, reject) => {
    syncContext.signal.addEventListener('abort', () => reject(syncContext.signal.reason), {
      once: true,
    });
  }));

  const preparation = scheduleRemainingWorkspacePreparation('client_manager', trips);
  for (let attempt = 0; attempt < 10 && mockPreloadManagerTrip.mock.calls.length < 2; attempt += 1) {
    await Promise.resolve();
  }
  expect(mockPreloadManagerTrip).toHaveBeenCalledTimes(2);

  useSessionStore.getState().setSession(OTHER_MANAGER_SESSION);

  await expect(preparation).rejects.toThrow(
    'The authenticated account changed while synchronization was running.',
  );
  expect(mockPreloadManagerTrip).toHaveBeenCalledTimes(2);
  const oldContext = mockPreloadManagerTrip.mock.calls[0]?.[2] as ImmutableSyncContext;
  expect(oldContext.signal.aborted).toBe(true);
});

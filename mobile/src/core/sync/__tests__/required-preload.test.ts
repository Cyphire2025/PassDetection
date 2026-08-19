import type { MobileSession } from '@/core/auth/types';
import { DEFAULT_TRIP_TIME_ZONE } from '@/core/localization/time-zone';
import type { ImmutableSyncContext } from '@/core/sync/sync-context';
import type { Trip } from '@/features/trips/model/trip';

import { preloadAuthenticatedWorkspace } from '../required-preload';

const PASSENGER_SESSION: MobileSession = {
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

const MANAGER_SESSION: MobileSession = {
  ...PASSENGER_SESSION,
  principal: {
    ...PASSENGER_SESSION.principal,
    principalType: 'client_manager',
    displayName: 'Manager One',
    email: 'manager@example.com',
    phoneNumber: null,
  },
};

const COORDINATOR_SESSION: MobileSession = {
  ...PASSENGER_SESSION,
  principal: {
    ...PASSENGER_SESSION.principal,
    principalType: 'coordinator',
    displayName: 'Coordinator One',
    email: 'coordinator@example.com',
    phoneNumber: null,
  },
};

let mockSession: MobileSession = PASSENGER_SESSION;
let mockSelectedTripId: string | null = null;
let mockSyncContext: ImmutableSyncContext;
const mockReleaseSyncContext = jest.fn();
const mockPreloadPassengerTrip = jest.fn();
const mockPreloadManagerTrips = jest.fn();
const mockPreloadCoordinatorTrips = jest.fn();
const mockRefreshTripsInContext = jest.fn();
const mockSetQueryData = jest.fn();
const mockCompleteRequiredPreparation = jest.fn();
const mockScheduleRemainingWorkspacePreparation = jest.fn();

jest.mock('@/core/auth/session-store', () => ({
  useSessionStore: {
    getState: () => ({ session: mockSession }),
  },
}));
jest.mock('@/core/query/query-client', () => ({
  mobileQueryClient: { setQueryData: (...args: unknown[]) => mockSetQueryData(...args) },
}));
jest.mock('@/features/content/data/passenger-preload', () => ({
  preloadPassengerTrip: (...args: unknown[]) => mockPreloadPassengerTrip(...args),
}));
jest.mock('@/features/content/data/manager-preload', () => ({
  preloadManagerTrips: (...args: unknown[]) => mockPreloadManagerTrips(...args),
}));
jest.mock('@/features/coordinator/data/coordinator-preload', () => ({
  preloadCoordinatorTrips: (...args: unknown[]) => mockPreloadCoordinatorTrips(...args),
}));
jest.mock('@/features/trips/data/trip-repository', () => ({
  refreshTripsInContext: (...args: unknown[]) => mockRefreshTripsInContext(...args),
}));
jest.mock('@/features/trips/state/selected-trip-store', () => ({
  useSelectedTripStore: {
    getState: () => ({ tripId: mockSelectedTripId }),
  },
}));
jest.mock('../required-preparation-lease', () => ({
  completeRequiredPreparation: (...args: unknown[]) => mockCompleteRequiredPreparation(...args),
}));
jest.mock('../sync-context', () => ({
  assertSyncContextActive: jest.fn(),
  captureSyncContext: () => ({ context: mockSyncContext, release: mockReleaseSyncContext }),
}));
jest.mock('../workspace-background-preload', () => ({
  scheduleRemainingWorkspacePreparation: (...args: unknown[]) => (
    mockScheduleRemainingWorkspacePreparation(...args)
  ),
}));

function trip(index: number, role: Trip['role'] = 'client_manager'): Trip {
  const suffix = String(index).padStart(12, '0');
  return {
    id: `44444444-4444-4444-8444-${suffix}`,
    name: `Trip ${index}`,
    destination: 'Singapore',
    travelDate: '2026-09-01',
    returnDate: '2026-09-05',
    timeZone: DEFAULT_TRIP_TIME_ZONE,
    role,
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
  mockSession = PASSENGER_SESSION;
  mockSelectedTripId = null;
  mockSyncContext = Object.freeze({
    sessionId: PASSENGER_SESSION.sessionId,
    namespace: `${PASSENGER_SESSION.principal.agencyId}.${PASSENGER_SESSION.principal.accountId}`,
    agencyId: PASSENGER_SESSION.principal.agencyId,
    principalId: PASSENGER_SESSION.principal.id,
    role: PASSENGER_SESSION.principal.principalType,
    signal: new AbortController().signal,
  });
  mockPreloadPassengerTrip.mockResolvedValue({
    tripId: '44444444-4444-4444-8444-444444444444',
    failedDownloads: 0,
    selectionRequired: false,
  });
  mockPreloadManagerTrips.mockResolvedValue({ failedDownloads: 0 });
  mockPreloadCoordinatorTrips.mockResolvedValue({ failedDownloads: 0 });
  mockScheduleRemainingWorkspacePreparation.mockResolvedValue({
    attemptedTrips: 0,
    failedTrips: 0,
  });
});

test('uses the already committed login principal and preserves passenger preparation', async () => {
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
  expect(mockRefreshTripsInContext).not.toHaveBeenCalled();
  expect(mockScheduleRemainingWorkspacePreparation).not.toHaveBeenCalled();
});

test('blocks a 500-trip manager login on only the first trip and schedules the other 499', async () => {
  mockSession = MANAGER_SESSION;
  mockSyncContext = Object.freeze({
    ...mockSyncContext,
    role: 'client_manager',
  });
  const trips = Array.from({ length: 500 }, (_, index) => trip(index));
  mockRefreshTripsInContext.mockResolvedValue({ trips, offline: false });

  await expect(preloadAuthenticatedWorkspace(jest.fn())).resolves.toEqual({
    destination: '/(manager)/(tabs)/groups',
  });

  expect(mockPreloadManagerTrips).toHaveBeenCalledTimes(1);
  expect(mockPreloadManagerTrips).toHaveBeenCalledWith(
    [trips[0]],
    expect.any(Function),
    mockSyncContext,
  );
  expect(mockScheduleRemainingWorkspacePreparation).toHaveBeenCalledWith(
    'client_manager',
    trips.slice(1),
  );
  expect(mockPreloadCoordinatorTrips).not.toHaveBeenCalled();
  expect(mockSetQueryData).toHaveBeenCalledWith(
    ['mobile-trips', mockSyncContext.namespace],
    { trips, offline: false },
  );
  expect(mockCompleteRequiredPreparation).toHaveBeenCalledWith(MANAGER_SESSION.sessionId);
});

test('uses an existing assigned selection as the one required coordinator trip', async () => {
  mockSession = COORDINATOR_SESSION;
  mockSyncContext = Object.freeze({
    ...mockSyncContext,
    role: 'coordinator',
  });
  const trips = [trip(1, 'coordinator'), trip(2, 'coordinator'), trip(3, 'coordinator')];
  mockSelectedTripId = trips[2]!.id;
  mockRefreshTripsInContext.mockResolvedValue({ trips, offline: false });

  await expect(preloadAuthenticatedWorkspace(jest.fn())).resolves.toEqual({
    destination: '/(coordinator)/(tabs)/groups',
  });

  expect(mockPreloadCoordinatorTrips).toHaveBeenCalledWith(
    [trips[2]],
    expect.any(Function),
    mockSyncContext,
  );
  expect(mockScheduleRemainingWorkspacePreparation).toHaveBeenCalledWith(
    'coordinator',
    [trips[0], trips[1]],
  );
});

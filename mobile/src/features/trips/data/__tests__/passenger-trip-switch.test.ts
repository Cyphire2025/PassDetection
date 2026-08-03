import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

import type { Trip } from '../../model/trip';
import {
  hasPreparedPassengerTripCache,
  PassengerTripSwitchInProgressError,
  switchToPassengerTrip,
} from '../passenger-trip-switch';

const TRIP_A: Trip = {
  id: '11111111-1111-4111-8111-111111111111',
  name: 'Singapore Leadership Trip',
  destination: 'Singapore',
  travelDate: '2026-09-01',
  returnDate: '2026-09-05',
  role: 'passenger',
  accessGeneration: 1,
  accessExpiresAt: null,
  itineraryVersion: 1,
  commonDocumentVersion: 1,
  announcementVersion: 1,
  updatedAt: '2026-08-03T00:00:00.000Z',
};

const TRIP_B: Trip = {
  ...TRIP_A,
  id: '22222222-2222-4222-8222-222222222222',
  name: 'Vietnam Leadership Trip',
  destination: 'Vietnam',
};

const BASE_SESSION: MobileSession = {
  accessToken: 'before-access',
  accessTokenExpiresAt: '2026-08-03T01:00:00.000Z',
  refreshTokenExpiresAt: '2026-09-03T00:00:00.000Z',
  sessionId: '33333333-3333-4333-8333-333333333333',
  networkMode: 'online',
  principal: {
    id: '44444444-4444-4444-8444-444444444444',
    accountId: '55555555-5555-4555-8555-555555555555',
    principalType: 'passenger',
    agencyId: '66666666-6666-4666-8666-666666666666',
    passengerId: '77777777-7777-4777-8777-777777777777',
    displayName: 'Passenger One',
    email: null,
    phoneNumber: '+919999999999',
    forcePasswordChange: false,
  },
};

const SWITCHED_SESSION: MobileSession = {
  ...BASE_SESSION,
  accessToken: 'switched-access',
  principal: {
    ...BASE_SESSION.principal,
    id: '88888888-8888-4888-8888-888888888888',
    passengerId: '99999999-9999-4999-8999-999999999999',
  },
};

const mockSwitchPassengerTripSession = jest.fn();
const mockGetFirstAsync = jest.fn();
const mockOpenAccountDatabase = jest.fn(async (_namespace: string) => ({
  getFirstAsync: mockGetFirstAsync,
}));
const mockSyncTrip = jest.fn();
const mockPreloadPassengerTrip = jest.fn();
const mockRememberPassengerTrip = jest.fn();
const mockCompleteRequiredPreparation = jest.fn();
const mockCancelRequiredPreparation = jest.fn();

jest.mock('@/core/auth/session-service', () => ({
  switchPassengerTripSession: (...args: unknown[]) => mockSwitchPassengerTripSession(...args),
}));

jest.mock('@/core/storage/database', () => ({
  openAccountDatabase: (namespace: string) => mockOpenAccountDatabase(namespace),
}));

jest.mock('@/core/sync/sync-service', () => ({
  syncTrip: (...args: unknown[]) => mockSyncTrip(...args),
}));

jest.mock('@/core/sync/required-preparation-lease', () => ({
  completeRequiredPreparation: (...args: unknown[]) => mockCompleteRequiredPreparation(...args),
  cancelRequiredPreparation: (...args: unknown[]) => mockCancelRequiredPreparation(...args),
}));

jest.mock('@/features/content/data/passenger-preload', () => ({
  preloadPassengerTrip: (...args: unknown[]) => mockPreloadPassengerTrip(...args),
}));

jest.mock('../passenger-trip-selection', () => ({
  eligiblePassengerTrip: (trips: Trip[], tripId: string) => (
    trips.find((trip) => trip.role === 'passenger' && trip.id === tripId) ?? null
  ),
  rememberPassengerTrip: (...args: unknown[]) => mockRememberPassengerTrip(...args),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function switchInput(tripId = TRIP_A.id) {
  return {
    tripId,
    trips: [TRIP_A, TRIP_B],
    onBlockingPreparation: jest.fn(),
    onProgress: jest.fn(),
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  useSessionStore.getState().setSession(BASE_SESSION);
  useSelectedTripStore.getState().clear();
  mockSwitchPassengerTripSession.mockImplementation(async () => {
    useSessionStore.getState().setSession(SWITCHED_SESSION);
    return SWITCHED_SESSION;
  });
  mockGetFirstAsync.mockResolvedValue({ prepared: 1 });
  mockRememberPassengerTrip.mockResolvedValue(TRIP_A);
  mockSyncTrip.mockResolvedValue({ tripId: TRIP_A.id });
  mockPreloadPassengerTrip.mockResolvedValue({
    tripId: TRIP_A.id,
    failedDownloads: 0,
    selectionRequired: false,
  });
});

afterEach(() => {
  useSessionStore.getState().clear();
  useSelectedTripStore.getState().clear();
});

test('opens an identity-bound prepared cache immediately and refreshes silently', async () => {
  const input = switchInput();

  await expect(switchToPassengerTrip(input)).resolves.toEqual({
    tripId: TRIP_A.id,
    usedPreparedCache: true,
    failedDownloads: 0,
  });

  expect(mockSwitchPassengerTripSession).toHaveBeenCalledWith(TRIP_A.id);
  expect(input.onBlockingPreparation).not.toHaveBeenCalled();
  expect(mockPreloadPassengerTrip).not.toHaveBeenCalled();
  expect(mockRememberPassengerTrip).toHaveBeenCalledWith(input.trips, TRIP_A.id);
  expect(useSelectedTripStore.getState().tripId).toBe(TRIP_A.id);
  expect(mockCompleteRequiredPreparation).toHaveBeenCalledWith(SWITCHED_SESSION.sessionId);
  expect(mockSyncTrip).toHaveBeenCalledWith(TRIP_A.id);
});

test('uses the blocking required preload only for an unprepared trip', async () => {
  mockGetFirstAsync.mockResolvedValue(null);
  const input = switchInput();

  await expect(switchToPassengerTrip(input)).resolves.toEqual({
    tripId: TRIP_A.id,
    usedPreparedCache: false,
    failedDownloads: 0,
  });

  expect(input.onBlockingPreparation).toHaveBeenCalledTimes(1);
  expect(mockPreloadPassengerTrip).toHaveBeenCalledWith(input.onProgress, TRIP_A.id);
  expect(mockSyncTrip).not.toHaveBeenCalled();
  expect(mockCompleteRequiredPreparation).toHaveBeenCalledWith(SWITCHED_SESSION.sessionId);
});

test('deduplicates repeated taps for one trip and rejects a competing trip switch', async () => {
  const pendingSwitch = deferred<MobileSession>();
  mockSwitchPassengerTripSession.mockImplementation(() => pendingSwitch.promise.then((session) => {
    useSessionStore.getState().setSession(session);
    return session;
  }));
  const input = switchInput();

  const first = switchToPassengerTrip(input);
  const duplicate = switchToPassengerTrip(input);
  const competing = switchToPassengerTrip(switchInput(TRIP_B.id));

  expect(duplicate).toBe(first);
  await expect(competing).rejects.toBeInstanceOf(PassengerTripSwitchInProgressError);
  expect(mockSwitchPassengerTripSession).toHaveBeenCalledTimes(1);

  pendingSwitch.resolve(SWITCHED_SESSION);
  await expect(first).resolves.toMatchObject({ tripId: TRIP_A.id });
});

test('fails closed when the authenticated context changes during the cache check', async () => {
  const pendingCache = deferred<{ prepared: number } | null>();
  mockGetFirstAsync.mockImplementation(() => pendingCache.promise);
  const input = switchInput();
  const switching = switchToPassengerTrip(input);

  await Promise.resolve();
  await Promise.resolve();
  useSessionStore.getState().setSession({
    ...SWITCHED_SESSION,
    sessionId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  });
  // Real logout/account activation clears the global selection synchronously.
  useSelectedTripStore.getState().clear();
  pendingCache.resolve({ prepared: 1 });

  await expect(switching).rejects.toThrow('active mobile session changed');
  expect(mockRememberPassengerTrip).not.toHaveBeenCalled();
  expect(useSelectedTripStore.getState().tripId).toBeNull();
  expect(mockPreloadPassengerTrip).not.toHaveBeenCalled();
  expect(mockSyncTrip).not.toHaveBeenCalled();
  expect(mockCompleteRequiredPreparation).not.toHaveBeenCalled();
});

test('scopes prepared-cache proof to account, trip, passenger, and purge state', async () => {
  useSessionStore.getState().setSession(SWITCHED_SESSION);
  const boundary = {
    sessionId: SWITCHED_SESSION.sessionId,
    namespace: `${SWITCHED_SESSION.principal.agencyId}.${SWITCHED_SESSION.principal.accountId}`,
    principalId: SWITCHED_SESSION.principal.id,
    passengerId: SWITCHED_SESSION.principal.passengerId!,
  };

  await expect(hasPreparedPassengerTripCache(TRIP_A.id, boundary)).resolves.toBe(true);

  expect(mockOpenAccountDatabase).toHaveBeenCalledWith(boundary.namespace);
  expect(mockGetFirstAsync).toHaveBeenCalledWith(
    expect.stringContaining('FROM trip_purge_tombstones purge'),
    boundary.namespace,
    TRIP_A.id,
    boundary.passengerId,
  );
  expect(mockGetFirstAsync.mock.calls[0]?.[0]).toEqual(expect.stringContaining('FROM qr_metadata qr'));
  expect(mockGetFirstAsync.mock.calls[0]?.[0]).toEqual(expect.stringContaining('cursor.last_synced_at IS NOT NULL'));
});

test('never touches local cache when the server rejects trip switching', async () => {
  mockSwitchPassengerTripSession.mockRejectedValue(new Error('Trip access was revoked.'));

  await expect(switchToPassengerTrip(switchInput())).rejects.toThrow('Trip access was revoked');

  expect(mockOpenAccountDatabase).not.toHaveBeenCalled();
  expect(mockRememberPassengerTrip).not.toHaveBeenCalled();
  expect(useSelectedTripStore.getState().tripId).toBeNull();
  expect(mockPreloadPassengerTrip).not.toHaveBeenCalled();
});

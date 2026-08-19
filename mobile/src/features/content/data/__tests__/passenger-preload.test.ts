import { ApiError } from '@/core/api/client';
import { DEFAULT_TRIP_TIME_ZONE } from '@/core/localization/time-zone';
import type { Trip } from '@/features/trips/model/trip';

import { preloadPassengerTrip } from '../passenger-preload';

const TRIP: Trip = {
  id: '44444444-4444-4444-8444-444444444444',
  name: 'Enterprise Trip',
  destination: 'Singapore',
  travelDate: '2026-09-01',
  returnDate: '2026-09-05',
  timeZone: DEFAULT_TRIP_TIME_ZONE,
  role: 'passenger',
  accessGeneration: 1,
  accessExpiresAt: null,
  itineraryVersion: 1,
  commonDocumentVersion: 1,
  announcementVersion: 1,
  updatedAt: '2026-08-03T00:00:00.000Z',
};

const mockRequestSync = jest.fn();
const mockRefreshTrips = jest.fn();
const mockRememberPassengerTrip = jest.fn();
const mockPassengerTripForRequiredPreload = jest.fn();
const mockScheduleTripDocumentHydration = jest.fn();
const mockSelectTrip = jest.fn();

jest.mock('@/core/sync/sync-service', () => ({
  scheduleTripDocumentHydration: (...args: unknown[]) => (
    mockScheduleTripDocumentHydration(...args)
  ),
}));
jest.mock('@/core/sync/sync-trigger', () => ({
  requestSync: (...args: unknown[]) => mockRequestSync(...args),
}));
jest.mock('@/features/trips/data/trip-repository', () => ({
  refreshTrips: (...args: unknown[]) => mockRefreshTrips(...args),
}));
jest.mock('@/features/trips/data/passenger-trip-selection', () => ({
  passengerTripForRequiredPreload: (...args: unknown[]) => (
    mockPassengerTripForRequiredPreload(...args)
  ),
  rememberPassengerTrip: (...args: unknown[]) => mockRememberPassengerTrip(...args),
  rememberedPassengerTrip: jest.fn(),
}));
jest.mock('@/features/trips/state/selected-trip-store', () => ({
  useSelectedTripStore: {
    getState: () => ({ selectTrip: mockSelectTrip }),
  },
}));
beforeEach(() => {
  jest.clearAllMocks();
  mockRefreshTrips.mockResolvedValue({ trips: [TRIP], offline: false });
  mockPassengerTripForRequiredPreload.mockReturnValue(TRIP);
  mockRememberPassengerTrip.mockResolvedValue(undefined);
});

test('synchronizes metadata once and leaves document bytes on the bounded background lane', async () => {
  mockRequestSync.mockResolvedValue({ results: [], failures: [] });
  const progress = jest.fn();

  await expect(preloadPassengerTrip(progress)).resolves.toEqual({
    tripId: TRIP.id,
    failedDownloads: 0,
    selectionRequired: false,
  });

  expect(mockRefreshTrips).toHaveBeenCalledTimes(1);
  expect(mockRequestSync).toHaveBeenCalledTimes(1);
  expect(mockRequestSync).toHaveBeenCalledWith({
    scope: 'trip',
    tripId: TRIP.id,
    reason: 'passenger-preload',
  });
  expect(mockScheduleTripDocumentHydration).not.toHaveBeenCalled();
  expect(progress).toHaveBeenLastCalledWith({
    percent: 100,
    message: 'Your trip is ready',
    completedLabel: 'Documents are being secured for offline use in the background',
  });
});

test('enters the cached workspace after a transient sync failure and schedules bounded hydration', async () => {
  mockRequestSync.mockRejectedValue(new TypeError('Network request failed'));
  const progress = jest.fn();

  await expect(preloadPassengerTrip(progress)).resolves.toEqual({
    tripId: TRIP.id,
    failedDownloads: 0,
    selectionRequired: false,
  });

  expect(mockScheduleTripDocumentHydration).toHaveBeenCalledWith(TRIP.id);
  expect(progress).toHaveBeenLastCalledWith({
    percent: 100,
    message: 'Your trip is available',
    completedLabel: 'Cached information is ready; latest updates and documents will retry in the background',
  });
});

test('does not block the cached shell on a document-byte outcome', async () => {
  mockRequestSync.mockResolvedValue({ results: [], failures: [] });
  await expect(preloadPassengerTrip(jest.fn())).resolves.toEqual({
    tripId: TRIP.id,
    failedDownloads: 0,
    selectionRequired: false,
  });
});

test('fails closed when the server rejects the authenticated trip boundary', async () => {
  const denied = new ApiError('Trip access was revoked.', 403, 'AUTHORIZATION_ERROR', null);
  mockRequestSync.mockRejectedValue(denied);

  await expect(preloadPassengerTrip(jest.fn())).rejects.toBe(denied);
  expect(mockScheduleTripDocumentHydration).not.toHaveBeenCalled();
});

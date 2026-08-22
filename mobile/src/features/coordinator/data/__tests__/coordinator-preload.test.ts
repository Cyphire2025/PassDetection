import { ApiError } from '@/core/api/client';
import type { Trip } from '@/features/trips/model/trip';
import { DEFAULT_TRIP_TIME_ZONE } from '@/core/localization/time-zone';

import { preloadCoordinatorTrip } from '../coordinator-preload';

const mockRequestSync = jest.fn();
const mockScheduleTripDocumentHydration = jest.fn();
const mockRefreshAttendanceSessions = jest.fn();

jest.mock('@/core/sync/sync-service', () => ({
  scheduleTripDocumentHydration: (...args: unknown[]) => (
    mockScheduleTripDocumentHydration(...args)
  ),
}));

jest.mock('@/core/sync/sync-trigger', () => ({
  requestSync: (...args: unknown[]) => mockRequestSync(...args),
}));

jest.mock('../attendance-sessions', () => ({
  refreshAttendanceSessions: (...args: unknown[]) => mockRefreshAttendanceSessions(...args),
}));

const TRIP: Trip = {
  id: '44444444-4444-4444-8444-444444444444',
  name: 'Coordinator Trip',
  destination: 'Singapore',
  travelDate: '2026-09-01',
  returnDate: '2026-09-05',
  timeZone: DEFAULT_TRIP_TIME_ZONE,
  role: 'coordinator',
  accessGeneration: 1,
  accessExpiresAt: null,
  itineraryVersion: 1,
  commonDocumentVersion: 1,
  announcementVersion: 1,
  updatedAt: '2026-08-03T00:00:00.000Z',
};

beforeEach(() => {
  jest.clearAllMocks();
  mockRefreshAttendanceSessions.mockResolvedValue({ items: [], selectedSessionId: null, offline: false });
});

test('prepares metadata once and leaves common-document bytes on the bounded background lane', async () => {
  mockRequestSync.mockResolvedValue({ results: [], failures: [] });

  await expect(preloadCoordinatorTrip(TRIP, jest.fn())).resolves.toEqual({ failedDownloads: 0 });

  expect(mockRequestSync).toHaveBeenCalledTimes(1);
  expect(mockRequestSync).toHaveBeenCalledWith(
    { scope: 'trip', tripId: TRIP.id, reason: 'coordinator-preload' },
    {},
  );
  expect(mockScheduleTripDocumentHydration).not.toHaveBeenCalled();
  expect(mockRefreshAttendanceSessions).toHaveBeenCalledTimes(1);
});

test('enters the cached workspace after a transient sync failure and schedules hydration', async () => {
  mockRequestSync.mockRejectedValue(new TypeError('Network request failed'));

  await expect(preloadCoordinatorTrip(TRIP, jest.fn())).resolves.toEqual({ failedDownloads: 0 });

  expect(mockScheduleTripDocumentHydration).toHaveBeenCalledWith(TRIP.id);
  expect(mockRefreshAttendanceSessions).toHaveBeenCalledTimes(1);
});

test('does not report ready when neither server nor cached attendance activities are available', async () => {
  mockRequestSync.mockResolvedValue({ results: [], failures: [] });
  const unavailable = new TypeError('Network request failed');
  mockRefreshAttendanceSessions.mockRejectedValueOnce(unavailable);
  const onProgress = jest.fn();

  await expect(preloadCoordinatorTrip(TRIP, onProgress)).rejects.toBe(unavailable);

  expect(onProgress).not.toHaveBeenCalledWith(expect.objectContaining({
    progress: 1,
  }));
});

test('fails closed when the server rejects the authenticated trip boundary', async () => {
  const denied = new ApiError('Trip access was revoked.', 403, 'AUTHORIZATION_ERROR', null);
  mockRequestSync.mockRejectedValue(denied);

  await expect(preloadCoordinatorTrip(TRIP, jest.fn())).rejects.toBe(denied);
  expect(mockScheduleTripDocumentHydration).not.toHaveBeenCalled();
  expect(mockRefreshAttendanceSessions).not.toHaveBeenCalled();
});

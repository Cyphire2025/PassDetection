import { ApiError } from '@/core/api/client';
import type { Trip } from '@/features/trips/model/trip';
import { DEFAULT_TRIP_TIME_ZONE } from '@/core/localization/time-zone';

import { preloadManagerTrips } from '../manager-preload';

const mockRequestSync = jest.fn();
const mockScheduleTripDocumentHydration = jest.fn();

jest.mock('@/core/sync/sync-service', () => ({
  scheduleTripDocumentHydration: (...args: unknown[]) => (
    mockScheduleTripDocumentHydration(...args)
  ),
}));

jest.mock('@/core/sync/sync-trigger', () => ({
  requestSync: (...args: unknown[]) => mockRequestSync(...args),
}));

const TRIP: Trip = {
  id: '44444444-4444-4444-8444-444444444444',
  name: 'Manager Trip',
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

beforeEach(() => {
  jest.clearAllMocks();
});

test('prepares metadata once and leaves common-document bytes on the bounded background lane', async () => {
  mockRequestSync.mockResolvedValue({ results: [], failures: [] });

  await expect(preloadManagerTrips([TRIP], jest.fn())).resolves.toEqual({ failedDownloads: 0 });

  expect(mockRequestSync).toHaveBeenCalledTimes(1);
  expect(mockRequestSync).toHaveBeenCalledWith(
    { scope: 'trip', tripId: TRIP.id, reason: 'manager-preload' },
    {},
  );
  expect(mockScheduleTripDocumentHydration).not.toHaveBeenCalled();
});

test('enters the cached workspace after a transient sync failure and schedules hydration', async () => {
  mockRequestSync.mockRejectedValue(new TypeError('Network request failed'));

  await expect(preloadManagerTrips([TRIP], jest.fn())).resolves.toEqual({ failedDownloads: 0 });

  expect(mockScheduleTripDocumentHydration).toHaveBeenCalledWith(TRIP.id);
});

test('fails closed when the server rejects the authenticated trip boundary', async () => {
  const denied = new ApiError('Trip access was revoked.', 403, 'AUTHORIZATION_ERROR', null);
  mockRequestSync.mockRejectedValue(denied);

  await expect(preloadManagerTrips([TRIP], jest.fn())).rejects.toBe(denied);
  expect(mockScheduleTripDocumentHydration).not.toHaveBeenCalled();
});

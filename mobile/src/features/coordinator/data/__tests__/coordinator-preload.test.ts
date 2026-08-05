import type { Trip } from '@/features/trips/model/trip';

import { preloadCoordinatorTrip } from '../coordinator-preload';

const mockSyncTrip = jest.fn();
const mockPrefetchCommonOfflineDocuments = jest.fn();
const mockPrefetchRequiredCommonOfflineDocuments = jest.fn();
const mockCountMissingRequiredOfflineDocuments = jest.fn();
const mockRefreshAttendanceSessions = jest.fn();

jest.mock('@/core/sync/sync-service', () => ({
  syncTrip: (...args: unknown[]) => mockSyncTrip(...args),
}));

jest.mock('@/features/content/data/content-repository', () => ({
  prefetchCommonOfflineDocuments: (...args: unknown[]) => (
    mockPrefetchCommonOfflineDocuments(...args)
  ),
  prefetchRequiredCommonOfflineDocuments: (...args: unknown[]) => (
    mockPrefetchRequiredCommonOfflineDocuments(...args)
  ),
  countMissingRequiredOfflineDocuments: (...args: unknown[]) => (
    mockCountMissingRequiredOfflineDocuments(...args)
  ),
  REQUIRED_COMMON_DOCUMENT_SCOPES: new Set(['common']),
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
  role: 'coordinator',
  accessGeneration: 1,
  accessExpiresAt: null,
  itineraryVersion: 1,
  commonDocumentVersion: 1,
  announcementVersion: 1,
  updatedAt: '2026-08-03T00:00:00.000Z',
};

const PREFETCH = {
  total: 1,
  completed: 1,
  failed: 0,
  currentDocumentName: null,
};

beforeEach(() => {
  jest.clearAllMocks();
  mockRefreshAttendanceSessions.mockResolvedValue({ items: [], selectedSessionId: null, offline: false });
  mockPrefetchRequiredCommonOfflineDocuments.mockResolvedValue({
    total: 0,
    completed: 0,
    failed: 0,
    currentDocumentName: null,
  });
  mockCountMissingRequiredOfflineDocuments.mockResolvedValue(0);
});

test('reuses sync document progress and does not revalidate every common file', async () => {
  mockSyncTrip.mockResolvedValue({
    tripId: TRIP.id,
    cursor: 1,
    changes: 1,
    changed: true,
    syncedAt: '2026-08-03T00:01:00.000Z',
    documentPrefetch: PREFETCH,
  });

  await expect(preloadCoordinatorTrip(TRIP, jest.fn())).resolves.toEqual({ failedDownloads: 0 });

  expect(mockSyncTrip).toHaveBeenCalledTimes(1);
  expect(mockSyncTrip).toHaveBeenCalledWith(TRIP.id, {
    onDocumentProgress: expect.any(Function),
  });
  expect(mockPrefetchCommonOfflineDocuments).not.toHaveBeenCalled();
  expect(mockPrefetchRequiredCommonOfflineDocuments).toHaveBeenCalledTimes(1);
  expect(mockRefreshAttendanceSessions).toHaveBeenCalledTimes(1);
});

test('uses the central size-aware prefetch after a transient sync failure', async () => {
  mockSyncTrip.mockRejectedValue(new TypeError('Network request failed'));
  mockPrefetchCommonOfflineDocuments.mockResolvedValue({ ...PREFETCH, completed: 0, failed: 1 });

  await expect(preloadCoordinatorTrip(TRIP, jest.fn())).resolves.toEqual({ failedDownloads: 1 });

  expect(mockPrefetchCommonOfflineDocuments).toHaveBeenCalledTimes(1);
  expect(mockPrefetchCommonOfflineDocuments).toHaveBeenCalledWith(TRIP.id, expect.any(Function));
  expect(mockPrefetchRequiredCommonOfflineDocuments).toHaveBeenCalledTimes(1);
  expect(mockRefreshAttendanceSessions).toHaveBeenCalledTimes(1);
});

test('blocks the coordinator workspace when a required common file is missing', async () => {
  mockSyncTrip.mockResolvedValue({
    tripId: TRIP.id,
    cursor: 2,
    changes: 1,
    changed: true,
    syncedAt: '2026-08-03T00:01:00.000Z',
    documentPrefetch: PREFETCH,
  });
  mockPrefetchRequiredCommonOfflineDocuments.mockResolvedValue({
    total: 1,
    completed: 0,
    failed: 1,
    currentDocumentName: null,
  });
  mockCountMissingRequiredOfflineDocuments.mockResolvedValue(1);

  await expect(preloadCoordinatorTrip(TRIP, jest.fn())).rejects.toThrow(
    'Required documents for Coordinator Trip could not be saved for offline use.',
  );
  expect(mockRefreshAttendanceSessions).not.toHaveBeenCalled();
});

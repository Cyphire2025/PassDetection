import type { Trip } from '@/features/trips/model/trip';

import { preloadManagerTrips } from '../manager-preload';

const mockSyncTrip = jest.fn();
const mockPrefetchCommonOfflineDocuments = jest.fn();
const mockPrefetchRequiredCommonOfflineDocuments = jest.fn();
const mockCountMissingRequiredOfflineDocuments = jest.fn();

jest.mock('@/core/sync/sync-service', () => ({
  syncTrip: (...args: unknown[]) => mockSyncTrip(...args),
}));

jest.mock('../content-repository', () => ({
  REQUIRED_COMMON_DOCUMENT_SCOPES: new Set(['common']),
  countMissingRequiredOfflineDocuments: (...args: unknown[]) => (
    mockCountMissingRequiredOfflineDocuments(...args)
  ),
  prefetchCommonOfflineDocuments: (...args: unknown[]) => (
    mockPrefetchCommonOfflineDocuments(...args)
  ),
  prefetchRequiredCommonOfflineDocuments: (...args: unknown[]) => (
    mockPrefetchRequiredCommonOfflineDocuments(...args)
  ),
}));

const TRIP: Trip = {
  id: '44444444-4444-4444-8444-444444444444',
  name: 'Manager Trip',
  destination: 'Singapore',
  travelDate: '2026-09-01',
  returnDate: '2026-09-05',
  role: 'client_manager',
  accessGeneration: 1,
  accessExpiresAt: null,
  itineraryVersion: 1,
  commonDocumentVersion: 1,
  announcementVersion: 1,
  updatedAt: '2026-08-03T00:00:00.000Z',
};

const PREFETCH = {
  total: 2,
  completed: 2,
  failed: 0,
  currentDocumentName: null,
};

beforeEach(() => {
  jest.clearAllMocks();
  mockPrefetchRequiredCommonOfflineDocuments.mockResolvedValue({
    total: 0,
    completed: 0,
    failed: 0,
    currentDocumentName: null,
  });
  mockCountMissingRequiredOfflineDocuments.mockResolvedValue(0);
});

test('reuses the common-document result produced by the manifest sync', async () => {
  mockSyncTrip.mockResolvedValue({
    tripId: TRIP.id,
    cursor: 1,
    changes: 1,
    changed: true,
    syncedAt: '2026-08-03T00:01:00.000Z',
    documentPrefetch: PREFETCH,
  });

  await expect(preloadManagerTrips([TRIP], jest.fn())).resolves.toEqual({ failedDownloads: 0 });

  expect(mockSyncTrip).toHaveBeenCalledTimes(1);
  expect(mockSyncTrip).toHaveBeenCalledWith(TRIP.id, {
    onDocumentProgress: expect.any(Function),
  });
  expect(mockPrefetchCommonOfflineDocuments).not.toHaveBeenCalled();
  expect(mockPrefetchRequiredCommonOfflineDocuments).toHaveBeenCalledWith(
    TRIP.id,
    expect.any(Function),
  );
});

test('runs one durable fallback prefetch only when manifest synchronization fails', async () => {
  mockSyncTrip.mockRejectedValue(new TypeError('Network request failed'));
  mockPrefetchCommonOfflineDocuments.mockResolvedValue({ ...PREFETCH, completed: 1, failed: 1 });

  await expect(preloadManagerTrips([TRIP], jest.fn())).resolves.toEqual({ failedDownloads: 1 });

  expect(mockPrefetchCommonOfflineDocuments).toHaveBeenCalledTimes(1);
  expect(mockPrefetchCommonOfflineDocuments).toHaveBeenCalledWith(TRIP.id, expect.any(Function));
});

test('does not enter a manager workspace while a required common document is missing', async () => {
  mockSyncTrip.mockResolvedValue({
    tripId: TRIP.id,
    cursor: 1,
    changes: 1,
    changed: true,
    syncedAt: '2026-08-03T00:01:00.000Z',
    documentPrefetch: PREFETCH,
  });
  mockCountMissingRequiredOfflineDocuments.mockResolvedValue(1);

  await expect(preloadManagerTrips([TRIP], jest.fn())).rejects.toThrow(
    'Required documents could not be saved for offline use',
  );
});

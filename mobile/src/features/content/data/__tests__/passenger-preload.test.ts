import { ApiError } from '@/core/api/client';
import type { Trip } from '@/features/trips/model/trip';

import { preloadPassengerTrip } from '../passenger-preload';

const TRIP: Trip = {
  id: '44444444-4444-4444-8444-444444444444',
  name: 'Enterprise Trip',
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

const mockSyncTrip = jest.fn();
const mockRefreshTrips = jest.fn();
const mockRememberPassengerTrip = jest.fn();
const mockPassengerTripForRequiredPreload = jest.fn();
const mockPrefetchPassengerOfflineDocuments = jest.fn();
const mockPrefetchRequiredPassengerOfflineDocuments = jest.fn();
const mockCountMissingRequiredOfflineDocuments = jest.fn();
const mockSelectTrip = jest.fn();

jest.mock('@/core/sync/sync-service', () => ({
  syncTrip: (...args: unknown[]) => mockSyncTrip(...args),
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
jest.mock('../content-repository', () => ({
  prefetchPassengerOfflineDocuments: (...args: unknown[]) => (
    mockPrefetchPassengerOfflineDocuments(...args)
  ),
  prefetchRequiredPassengerOfflineDocuments: (...args: unknown[]) => (
    mockPrefetchRequiredPassengerOfflineDocuments(...args)
  ),
  countMissingRequiredOfflineDocuments: (...args: unknown[]) => (
    mockCountMissingRequiredOfflineDocuments(...args)
  ),
  REQUIRED_PASSENGER_DOCUMENT_SCOPES: new Set(['personal', 'common']),
}));

beforeEach(() => {
  jest.clearAllMocks();
  mockRefreshTrips.mockResolvedValue({ trips: [TRIP], offline: false });
  mockPassengerTripForRequiredPreload.mockReturnValue(TRIP);
  mockRememberPassengerTrip.mockResolvedValue(undefined);
  mockPrefetchRequiredPassengerOfflineDocuments.mockResolvedValue({
    total: 0,
    completed: 0,
    failed: 0,
    currentDocumentName: null,
  });
  mockCountMissingRequiredOfflineDocuments.mockResolvedValue(0);
});

test('uses one manifest sync and reuses its document preload outcome', async () => {
  mockSyncTrip.mockImplementation(async (_tripId: string, options: {
    onDocumentProgress?: (progress: {
      total: number;
      completed: number;
      failed: number;
      currentDocumentName: string | null;
    }) => void;
  }) => {
    const documentPrefetch = {
      total: 2,
      completed: 2,
      failed: 0,
      currentDocumentName: null,
    };
    options.onDocumentProgress?.(documentPrefetch);
    return {
      tripId: TRIP.id,
      cursor: 3,
      changes: 3,
      changed: true,
      syncedAt: '2026-08-03T00:01:00.000Z',
      documentPrefetch,
    };
  });
  const progress = jest.fn();

  await expect(preloadPassengerTrip(progress)).resolves.toEqual({
    tripId: TRIP.id,
    failedDownloads: 0,
    selectionRequired: false,
  });

  expect(mockRefreshTrips).toHaveBeenCalledTimes(1);
  expect(mockSyncTrip).toHaveBeenCalledTimes(1);
  expect(mockPrefetchPassengerOfflineDocuments).not.toHaveBeenCalled();
  expect(mockPrefetchRequiredPassengerOfflineDocuments).toHaveBeenCalledTimes(1);
  expect(progress).toHaveBeenLastCalledWith({
    percent: 100,
    message: 'Your trip is ready',
    completedLabel: 'All 2 documents are ready offline',
  });
});

test('enters the cached workspace after a transient sync failure and schedules silent retry', async () => {
  mockSyncTrip.mockRejectedValue(new Error('Network request failed'));
  mockPrefetchPassengerOfflineDocuments.mockResolvedValue({
    total: 1,
    completed: 1,
    failed: 0,
    currentDocumentName: null,
  });
  const progress = jest.fn();

  await expect(preloadPassengerTrip(progress)).resolves.toEqual({
    tripId: TRIP.id,
    failedDownloads: 0,
    selectionRequired: false,
  });

  expect(mockPrefetchPassengerOfflineDocuments).toHaveBeenCalledTimes(1);
  expect(mockPrefetchRequiredPassengerOfflineDocuments).toHaveBeenCalledTimes(1);
  expect(progress).toHaveBeenLastCalledWith({
    percent: 100,
    message: 'Your trip is available',
    completedLabel: 'All 1 documents are ready offline; latest updates will retry in the background',
  });
});

test('blocks navigation when a newly published required document is still missing', async () => {
  mockSyncTrip.mockResolvedValue({
    tripId: TRIP.id,
    cursor: 2,
    changes: 1,
    changed: true,
    syncedAt: '2026-08-03T00:01:00.000Z',
    documentPrefetch: {
      total: 1,
      completed: 0,
      failed: 1,
      currentDocumentName: null,
    },
  });
  mockPrefetchRequiredPassengerOfflineDocuments.mockResolvedValue({
    total: 1,
    completed: 0,
    failed: 1,
    currentDocumentName: null,
  });
  mockCountMissingRequiredOfflineDocuments.mockResolvedValue(1);

  await expect(preloadPassengerTrip(jest.fn())).rejects.toThrow(
    'Required documents could not be saved securely',
  );
});

test('fails closed when the server rejects the authenticated trip boundary', async () => {
  const denied = new ApiError('Trip access was revoked.', 403, 'AUTHORIZATION_ERROR', null);
  mockSyncTrip.mockRejectedValue(denied);

  await expect(preloadPassengerTrip(jest.fn())).rejects.toBe(denied);
  expect(mockPrefetchPassengerOfflineDocuments).not.toHaveBeenCalled();
});

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react-native';
import type { PropsWithChildren } from 'react';

import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';
import type { DocumentWithOfflineState } from '@/features/content/data/content-repository';

import { useCacheFirstTripQuery, useCommonDocuments } from '../use-content';

const mockLocalDocuments = jest.fn();
const mockPrefetchCommonDocuments = jest.fn();
const mockRequestSync = jest.fn();

jest.mock('../../data/content-repository', () => ({
  loadMeal: jest.fn(),
  loadQr: jest.fn(),
  loadReadiness: jest.fn(),
  loadRoom: jest.fn(),
  localAnnouncements: jest.fn(async () => []),
  localDocuments: (...args: unknown[]) => mockLocalDocuments(...args),
  localMeal: jest.fn(),
  localQr: jest.fn(),
  localReadiness: jest.fn(),
  localRoom: jest.fn(),
  prefetchCommonOfflineDocuments: (...args: unknown[]) => mockPrefetchCommonDocuments(...args),
  refreshAnnouncements: jest.fn(),
  refreshCommonDocuments: jest.fn(),
  refreshDocuments: jest.fn(),
}));
jest.mock('@/core/sync/sync-trigger', () => ({
  requestSync: (...args: unknown[]) => mockRequestSync(...args),
}));

const session: MobileSession = {
  accessToken: 'access-account-a',
  accessTokenExpiresAt: '2030-01-01T00:00:00.000Z',
  refreshTokenExpiresAt: '2030-02-01T00:00:00.000Z',
  sessionId: 'session-account-a',
  networkMode: 'online',
  principal: {
    id: 'account-a',
    accountId: 'account-a',
    principalType: 'passenger',
    agencyId: 'agency-a',
    passengerId: 'passenger-a',
    displayName: 'Passenger',
    email: null,
    phoneNumber: null,
    forcePasswordChange: false,
  },
};

const wrapperFor = (client: QueryClient) => function QueryWrapper({ children }: PropsWithChildren) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
};

describe('useCacheFirstTripQuery', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useSessionStore.getState().setSession(session);
    mockLocalDocuments.mockResolvedValue([]);
    mockRequestSync.mockResolvedValue({
      results: [], failures: [], requestedTripCount: 0, tripsChanged: false, removedTripIds: [],
    });
    mockPrefetchCommonDocuments.mockResolvedValue({
      total: 0,
      completed: 0,
      failed: 0,
      currentDocumentName: null,
    });
  });
  afterEach(() => useSessionStore.getState().clear());

  it('uses only the local projection and routes explicit refetch through the coordinator', async () => {
    type TestDocuments = { items: { id: string }[]; offline: boolean };
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: 60_000 } },
    });
    const cached = jest.fn(async (): Promise<TestDocuments> => ({ items: [], offline: true }));
    const { result, unmount } = await renderHook(() => useCacheFirstTripQuery<TestDocuments>({
      keyPrefix: 'test-documents',
      tripId: 'trip-a',
      cached,
    }), { wrapper: wrapperFor(client) });

    await waitFor(() => expect(cached).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.data?.items).toEqual([]));
    await act(async () => { await result.current.refetch(); });
    expect(mockRequestSync).toHaveBeenCalledWith({
      scope: 'trip',
      tripId: 'trip-a',
      reason: 'manual-test-documents',
    });

    await act(async () => unmount());
    client.clear();
  });

  it('downloads a newly published common document and updates its local state', async () => {
    const document: DocumentWithOfflineState = {
      id: 'document-a',
      trip_id: 'trip-a',
      passenger_id: null,
      scope: 'common',
      category: 'itinerary_pdf',
      display_name: 'Itinerary',
      content_type: 'application/pdf',
      size_bytes: 1_024,
      version: 1,
      checksum_sha256: 'a'.repeat(64),
      offline_available: true,
      metadata_state: 'ready',
      updated_at: '2030-01-01T00:00:00.000Z',
      revoked_at: null,
      offline: false,
      offlineVersion: null,
    };
    mockLocalDocuments
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([document])
      .mockResolvedValueOnce([{ ...document, offline: true, offlineVersion: 1 }]);
    mockPrefetchCommonDocuments.mockResolvedValue({
      total: 1,
      completed: 1,
      failed: 0,
      currentDocumentName: null,
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    const { result, unmount } = await renderHook(
      () => useCommonDocuments('trip-a'),
      { wrapper: wrapperFor(client) },
    );

    await waitFor(() => expect(mockPrefetchCommonDocuments).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(result.current.data?.items[0]).toMatchObject({
      id: 'document-a',
      offline: true,
      offlineVersion: 1,
    }));
    expect(mockLocalDocuments).toHaveBeenLastCalledWith(
      'trip-a',
      expect.any(Object),
      'common',
    );

    await act(async () => unmount());
    client.clear();
  });
});

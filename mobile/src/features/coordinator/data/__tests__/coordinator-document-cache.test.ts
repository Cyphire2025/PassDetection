import type { DocumentWithOfflineState } from '@/features/content/data/content-repository';

import {
  ensureCoordinatorDocumentOffline,
  prefetchCoordinatorCommonDocuments,
} from '../coordinator-document-cache';

const mockCacheDocument = jest.fn();
const mockGetDocument = jest.fn();
const mockPrefetchCommonOfflineDocuments = jest.fn();
const mockAssertSyncContextActive = jest.fn();
const mockRelease = jest.fn();
const mockAccountController = new AbortController();

jest.mock('@/features/content/data/content-repository', () => ({
  cacheDocument: (...args: unknown[]) => mockCacheDocument(...args),
  getDocument: (...args: unknown[]) => mockGetDocument(...args),
  prefetchCommonOfflineDocuments: (...args: unknown[]) => (
    mockPrefetchCommonOfflineDocuments(...args)
  ),
}));

jest.mock('@/core/sync/sync-context', () => ({
  assertSyncContextActive: (...args: unknown[]) => mockAssertSyncContextActive(...args),
  captureSyncContext: () => ({
    context: {
      sessionId: 'session-a',
      namespace: 'agency-a:account-a',
      agencyId: 'agency-a',
      principalId: 'principal-a',
      role: 'coordinator',
      signal: mockAccountController.signal,
    },
    release: mockRelease,
  }),
}));

const DOCUMENT: DocumentWithOfflineState = {
  id: '55555555-5555-4555-8555-555555555555',
  trip_id: '44444444-4444-4444-8444-444444444444',
  passenger_id: null,
  scope: 'common',
  category: 'itinerary_pdf',
  display_name: 'Itinerary',
  content_type: 'application/pdf',
  size_bytes: 1024,
  version: 2,
  checksum_sha256: 'a'.repeat(64),
  offline_available: true,
  metadata_state: 'ready',
  updated_at: '2026-08-03T00:00:00.000Z',
  revoked_at: null,
  offline: true,
  offlineVersion: 2,
};

beforeEach(() => {
  jest.clearAllMocks();
});

test('delegates screen prefetch to the central common-document worker with cancellation', async () => {
  const controller = new AbortController();
  mockPrefetchCommonOfflineDocuments.mockImplementation(async (
    _tripId: string,
    _onProgress: unknown,
    context: { signal: AbortSignal },
  ) => {
    expect(context.signal.aborted).toBe(false);
    controller.abort();
    expect(context.signal.aborted).toBe(true);
    return { total: 0, completed: 0, failed: 0, currentDocumentName: null };
  });

  await expect(prefetchCoordinatorCommonDocuments(DOCUMENT.trip_id, controller.signal)).resolves.toEqual({
    total: 0,
    completed: 0,
    failed: 0,
    currentDocumentName: null,
  });

  expect(mockPrefetchCommonOfflineDocuments).toHaveBeenCalledTimes(1);
  expect(mockRelease).toHaveBeenCalledTimes(1);
});

test('does not decrypt and revalidate an already-current offline document', async () => {
  mockGetDocument.mockResolvedValue(DOCUMENT);

  await expect(ensureCoordinatorDocumentOffline(DOCUMENT)).resolves.toEqual(DOCUMENT);

  expect(mockGetDocument).toHaveBeenCalledWith(DOCUMENT.trip_id, DOCUMENT.id);
  expect(mockCacheDocument).not.toHaveBeenCalled();
  expect(mockRelease).toHaveBeenCalledTimes(1);
});

test('downloads a missing or stale document exactly once', async () => {
  const stale = { ...DOCUMENT, offline: false, offlineVersion: null };
  mockGetDocument.mockResolvedValue(stale);
  mockCacheDocument.mockResolvedValue(undefined);

  await expect(ensureCoordinatorDocumentOffline(stale)).resolves.toEqual(stale);

  expect(mockCacheDocument).toHaveBeenCalledTimes(1);
  expect(mockCacheDocument).toHaveBeenCalledWith(
    stale,
    expect.objectContaining({ namespace: 'agency-a:account-a' }),
    expect.any(AbortSignal),
  );
});

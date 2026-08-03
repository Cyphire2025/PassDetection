import {
  cacheDocument,
  getDocument,
  prefetchCommonOfflineDocuments,
  type DocumentWithOfflineState,
  type OfflinePrefetchProgress,
} from '@/features/content/data/content-repository';
import {
  assertSyncContextActive,
  captureSyncContext,
  type ImmutableSyncContext,
} from '@/core/sync/sync-context';

function contextWithCancellation(
  context: ImmutableSyncContext,
  signal?: AbortSignal,
): ImmutableSyncContext {
  if (!signal) return context;
  return Object.freeze({
    ...context,
    signal: AbortSignal.any([context.signal, signal]),
  });
}

export async function prefetchCoordinatorCommonDocuments(
  tripId: string,
  signal?: AbortSignal,
): Promise<OfflinePrefetchProgress> {
  const lease = captureSyncContext();
  const context = contextWithCancellation(lease.context, signal);
  try {
    assertSyncContextActive(context);
    return await prefetchCommonOfflineDocuments(tripId, undefined, context);
  } finally {
    lease.release();
  }
}

export async function ensureCoordinatorDocumentOffline(
  document: DocumentWithOfflineState,
  signal?: AbortSignal,
): Promise<DocumentWithOfflineState> {
  const lease = captureSyncContext();
  const context = contextWithCancellation(lease.context, signal);
  try {
    assertSyncContextActive(context);
    const current = await getDocument(document.trip_id, document.id);
    assertSyncContextActive(context);
    if (!current || !current.offline_available || current.metadata_state !== 'ready') {
      throw new Error('This document is no longer available for secure offline access.');
    }
    if (!current.offline || current.offlineVersion !== current.version) {
      await cacheDocument(current, context, context.signal);
    }
    assertSyncContextActive(context);
    return current;
  } finally {
    lease.release();
  }
}

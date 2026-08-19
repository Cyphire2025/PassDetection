import type { QueryClient } from '@tanstack/react-query';

import { mobileQueryClient } from '@/core/query/query-client';

import {
  assertSyncContextActive,
  type ImmutableSyncContext,
} from './sync-context';
import {
  changedSyncTripIds,
  queryKeyMatchesChangedProjection,
} from './sync-runtime-policy';
import type { SyncAllTripsSummary } from './sync-service';

/**
 * Publishes committed SQLite projections to active observers. Every matched
 * query function is local-only; remote reconciliation remains exclusively in
 * the sync coordinator. Unrelated operational queries are deliberately not
 * invalidated merely because their key contains the same trip identifier.
 */
export async function publishSyncSummary(
  summary: SyncAllTripsSummary,
  syncContext: ImmutableSyncContext,
  queryClient: QueryClient = mobileQueryClient,
): Promise<void> {
  assertSyncContextActive(syncContext);
  for (const tripId of summary.removedTripIds) {
    await queryClient.cancelQueries({
      predicate: (query) => query.queryKey.includes(syncContext.namespace)
        && query.queryKey.includes(tripId),
    });
    assertSyncContextActive(syncContext);
    queryClient.removeQueries({
      predicate: (query) => query.queryKey.includes(syncContext.namespace)
        && query.queryKey.includes(tripId),
    });
  }

  const changedTripIds = changedSyncTripIds(summary.results);
  const publications: Promise<unknown>[] = [];
  if (changedTripIds.length > 0) {
    publications.push(queryClient.invalidateQueries({
      predicate: (query) => queryKeyMatchesChangedProjection(
        query.queryKey,
        changedTripIds,
      ) && query.queryKey.includes(syncContext.namespace),
      refetchType: 'active',
    }));
  }
  if (summary.tripsChanged || changedTripIds.length > 0) {
    publications.push(queryClient.invalidateQueries({
      predicate: (query) => query.queryKey[0] === 'mobile-trips'
        && query.queryKey.includes(syncContext.namespace),
      refetchType: 'active',
    }));
  }
  await Promise.all(publications);
  assertSyncContextActive(syncContext);
}

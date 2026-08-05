import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef } from 'react';

import { useSessionStore } from '@/core/auth/session-store';
import { accountNamespace } from '@/core/auth/types';
import { usePersistentQueryHydration } from '@/core/query/use-persistent-query-hydration';
import { captureSyncContext } from '@/core/sync/sync-context';

import {
  loadMeal,
  loadQr,
  loadReadiness,
  loadRoom,
  localAnnouncements,
  localDocuments,
  localMeal,
  localQr,
  localReadiness,
  localRoom,
  prefetchCommonOfflineDocuments,
  refreshAnnouncements,
  refreshCommonDocuments,
  refreshDocuments,
} from '../data/content-repository';

type CommonDocumentsResult = Awaited<ReturnType<typeof refreshCommonDocuments>>;

type CacheFirstQueryOptions<T> = {
  keyPrefix: string;
  tripId: string | null;
  refresh: (tripId: string) => Promise<T>;
  cached: (tripId: string) => Promise<T | null>;
};

const cachedAnnouncements = async (tripId: string) => ({
  items: await localAnnouncements(tripId),
  offline: true as const,
});
const cachedDocuments = async (tripId: string) => ({
  items: await localDocuments(tripId),
  offline: true as const,
});
const cachedCommonDocuments = async (tripId: string) => ({
  items: await localDocuments(tripId, undefined, 'common'),
  offline: true as const,
});
const cachedQr = async (tripId: string) => {
  const qr = await localQr(tripId);
  return qr ? { qr, offline: true as const } : null;
};

function useCacheFirstTripQueryState<T>({
  keyPrefix,
  tripId,
  refresh,
  cached,
}: CacheFirstQueryOptions<T>) {
  const agencyId = useSessionStore((state) => state.session?.principal.agencyId ?? null);
  const accountId = useSessionStore((state) => state.session?.principal.accountId ?? null);
  const accountKey = agencyId && accountId ? accountNamespace({ agencyId, accountId }) : null;
  // Keep the trip id in the second position so existing prefix invalidations continue to work,
  // while the immutable account namespace prevents in-memory cache reuse across tenants/users.
  const queryKey = useMemo(
    () => [keyPrefix, tripId, accountKey] as const,
    [accountKey, keyPrefix, tripId],
  );
  const loadCached = useCallback(
    () => cached(tripId!),
    [cached, tripId],
  );
  const cacheHydrated = usePersistentQueryHydration({
    accountKey,
    hydrationKey: tripId ? `${keyPrefix}:${tripId}` : null,
    queryKey,
    load: loadCached,
  });
  const query = useQuery({
    queryKey,
    queryFn: () => refresh(tripId!),
    enabled: Boolean(accountKey && tripId && cacheHydrated),
    // A persisted snapshot is the instant first paint, not proof that the
    // server has no newer data. Always reconcile once after hydration.
    staleTime: 0,
    refetchOnMount: 'always',
  });

  return { accountKey, query, queryKey };
}

export function useCacheFirstTripQuery<T>(options: CacheFirstQueryOptions<T>) {
  return useCacheFirstTripQueryState(options).query;
}

export function useAnnouncements(tripId: string | null) {
  return useCacheFirstTripQuery({
    keyPrefix: 'trip-announcements',
    tripId,
    refresh: refreshAnnouncements,
    cached: cachedAnnouncements,
  });
}

export function useDocuments(tripId: string | null) {
  return useCacheFirstTripQuery({
    keyPrefix: 'trip-documents',
    tripId,
    refresh: refreshDocuments,
    cached: cachedDocuments,
  });
}

export function useCommonDocuments(tripId: string | null) {
  const queryClient = useQueryClient();
  const { accountKey, query, queryKey } = useCacheFirstTripQueryState({
    keyPrefix: 'trip-common-documents',
    tripId,
    refresh: refreshCommonDocuments,
    cached: cachedCommonDocuments,
  });
  const attemptedPrefetch = useRef<string | null>(null);
  const pendingSignature = useMemo(
    () => (query.data?.items ?? [])
      .filter((document) => (
        document.offline_available
        && document.metadata_state === 'ready'
        && (!document.offline || document.offlineVersion !== document.version)
      ))
      .map((document) => `${document.id}:${document.version}`)
      .sort()
      .join('|'),
    [query.data?.items],
  );
  const prefetchKey = accountKey && tripId && pendingSignature
    ? `${accountKey}\u001f${tripId}\u001f${pendingSignature}`
    : null;

  useEffect(() => {
    if (
      !tripId
      || !accountKey
      || !prefetchKey
      || attemptedPrefetch.current === prefetchKey
    ) return;

    attemptedPrefetch.current = prefetchKey;
    const expectedAccountKey = accountKey;
    const controller = new AbortController();
    let lease: ReturnType<typeof captureSyncContext>;
    try {
      lease = captureSyncContext();
    } catch {
      attemptedPrefetch.current = null;
      return;
    }
    let leaseReleased = false;
    const releaseLease = () => {
      if (leaseReleased) return;
      leaseReleased = true;
      lease.release();
    };
    const syncContext = Object.freeze({
      ...lease.context,
      signal: AbortSignal.any([lease.context.signal, controller.signal]),
    });
    let active = true;

    void prefetchCommonOfflineDocuments(tripId, undefined, syncContext)
      .then(async () => {
        if (!active || syncContext.signal.aborted) return;
        const session = useSessionStore.getState().session;
        const currentAccountKey = session
          ? accountNamespace({
              agencyId: session.principal.agencyId,
              accountId: session.principal.accountId,
            })
          : null;
        if (currentAccountKey !== expectedAccountKey) return;
        const items = await localDocuments(tripId, syncContext, 'common');
        if (!active || syncContext.signal.aborted) return;
        queryClient.setQueryData<CommonDocumentsResult>(queryKey, (current) => ({
          items,
          offline: current?.offline ?? false,
        }));
      })
      .catch(() => {
        // The durable download queue and the next synchronization pass retain
        // retry ownership. Keep the last usable document list on screen.
      })
      .finally(releaseLease);

    return () => {
      active = false;
      controller.abort();
      releaseLease();
    };
  }, [accountKey, prefetchKey, queryClient, queryKey, tripId]);

  return query;
}

export function useQr(tripId: string | null) {
  return useCacheFirstTripQuery({
    keyPrefix: 'trip-qr',
    tripId,
    refresh: loadQr,
    cached: cachedQr,
  });
}

export function useRoom(tripId: string | null) {
  return useCacheFirstTripQuery({
    keyPrefix: 'trip-room',
    tripId,
    refresh: loadRoom,
    cached: localRoom,
  });
}

export function useMeal(tripId: string | null) {
  return useCacheFirstTripQuery({
    keyPrefix: 'trip-meal',
    tripId,
    refresh: loadMeal,
    cached: localMeal,
  });
}

export function useReadiness(tripId: string | null) {
  return useCacheFirstTripQuery({
    keyPrefix: 'manager-readiness',
    tripId,
    refresh: loadReadiness,
    cached: localReadiness,
  });
}

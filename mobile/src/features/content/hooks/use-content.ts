import { useQuery } from '@tanstack/react-query';
import { useCallback, useMemo } from 'react';

import { useSessionStore } from '@/core/auth/session-store';
import { accountNamespace } from '@/core/auth/types';
import { usePersistentQueryHydration } from '@/core/query/use-persistent-query-hydration';

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
  refreshAnnouncements,
  refreshCommonDocuments,
  refreshDocuments,
} from '../data/content-repository';

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

export function useCacheFirstTripQuery<T>({
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
  });

  return query;
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
  return useCacheFirstTripQuery({
    keyPrefix: 'trip-common-documents',
    tripId,
    refresh: refreshCommonDocuments,
    cached: cachedCommonDocuments,
  });
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

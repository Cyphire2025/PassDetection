import { useQuery } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo } from 'react';

import { useSessionStore } from '@/core/auth/session-store';
import { accountNamespace } from '@/core/auth/types';
import { withAccountQueryContext } from '@/core/query/account-query-context';
import { usePersistentQueryHydration } from '@/core/query/use-persistent-query-hydration';
import { requestSync } from '@/core/sync/sync-trigger';
import {
  localTrips,
  localTripsInContext,
} from '@/features/trips/data/trip-repository';
import type { Trip } from '@/features/trips/model/trip';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

import { useCoordinatorTripStore } from '../state/coordinator-trip-store';

const EMPTY_TRIPS: Trip[] = [];

export function useCoordinatorTrips() {
  const agencyId = useSessionStore((state) => state.session?.principal.agencyId ?? null);
  const accountId = useSessionStore((state) => state.session?.principal.principalType === 'coordinator'
    ? state.session.principal.accountId
    : null);
  const accountKey = agencyId && accountId ? accountNamespace({ agencyId, accountId }) : null;
  const storedAccountKey = useCoordinatorTripStore((state) => state.accountKey);
  const storedTripId = useCoordinatorTripStore((state) => state.tripId);
  const activateAccount = useCoordinatorTripStore((state) => state.activateAccount);
  const selectStoredTrip = useCoordinatorTripStore((state) => state.selectTrip);
  const clearStoredSelection = useCoordinatorTripStore((state) => state.clearSelection);

  const queryKey = useMemo(() => ['mobile-trips', accountKey] as const, [accountKey]);
  const loadCachedTrips = useCallback(async () => {
    const trips = await localTrips();
    return trips.length ? { trips, offline: true as const } : null;
  }, []);
  const cacheHydrated = usePersistentQueryHydration({
    accountKey,
    hydrationKey: 'mobile-trips',
    queryKey,
    load: loadCachedTrips,
  });
  const query = useQuery({
    queryKey,
    queryFn: ({ signal }) => withAccountQueryContext(
      signal,
      async (context) => ({
        trips: await localTripsInContext(context),
        offline: true as const,
      }),
    ),
    enabled: Boolean(accountKey && cacheHydrated),
    staleTime: 15_000,
  });
  const localRefetch = query.refetch;
  const coordinatedRefetch = useCallback((
    options?: Parameters<typeof localRefetch>[0],
  ) => requestSync({ scope: 'full', reason: 'manual-coordinator-trips' })
    .then(() => localRefetch(options)), [localRefetch]);
  const storedSelectedTripId = storedAccountKey === accountKey ? storedTripId : null;
  const selectedTripId = query.data && storedSelectedTripId
    && !query.data.trips.some((trip) => trip.id === storedSelectedTripId)
    ? null
    : storedSelectedTripId;

  useEffect(() => {
    activateAccount(accountKey);
  }, [accountKey, activateAccount]);

  useEffect(() => {
    if (!accountKey || !storedSelectedTripId || !query.data) return;
    if (!query.data.trips.some((trip) => trip.id === storedSelectedTripId)) {
      clearStoredSelection(accountKey);
    }
  }, [accountKey, clearStoredSelection, query.data, storedSelectedTripId]);

  // The coordinator selector is account scoped, while the shared selector tells the sync
  // runtime which single trip to refresh. Keep them aligned only after authorization succeeds.
  useEffect(() => {
    const shared = useSelectedTripStore.getState();
    if (!accountKey || !selectedTripId) {
      if (shared.tripId) shared.clear();
      return;
    }
    if (shared.tripId !== selectedTripId) shared.selectTrip(selectedTripId);
  }, [accountKey, selectedTripId]);

  const selectTrip = useCallback((tripId: string) => {
    if (accountKey) selectStoredTrip(accountKey, tripId);
  }, [accountKey, selectStoredTrip]);

  const clearSelection = useCallback(() => {
    if (accountKey) clearStoredSelection(accountKey);
  }, [accountKey, clearStoredSelection]);

  const trips = query.data?.trips ?? EMPTY_TRIPS;
  return {
    ...query,
    refetch: coordinatedRefetch,
    trips,
    offline: query.data?.offline ?? false,
    selectedTripId,
    selectedTrip: trips.find((trip) => trip.id === selectedTripId) ?? null,
    selectTrip,
    clearSelection,
  };
}

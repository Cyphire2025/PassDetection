import { useQuery } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { useSessionStore } from '@/core/auth/session-store';
import { accountNamespace } from '@/core/auth/types';
import { withAccountQueryContext } from '@/core/query/account-query-context';
import { usePersistentQueryHydration } from '@/core/query/use-persistent-query-hydration';
import { requestSync } from '@/core/sync/sync-trigger';

import { localTrips, localTripsInContext } from '../data/trip-repository';
import { rememberPassengerTrip, rememberedPassengerTrip } from '../data/passenger-trip-selection';
import { useSelectedTripStore } from '../state/selected-trip-store';

export function useTrips() {
  const agencyId = useSessionStore((state) => state.session?.principal.agencyId);
  const accountId = useSessionStore((state) => state.session?.principal.accountId);
  const principalType = useSessionStore((state) => state.session?.principal.principalType);
  const accountKey = agencyId && accountId ? accountNamespace({ agencyId, accountId }) : null;
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
  });
  const localRefetch = query.refetch;
  const coordinatedRefetch = useCallback((
    options?: Parameters<typeof localRefetch>[0],
  ) => requestSync({ scope: 'full', reason: 'manual-mobile-trips' })
    .then(() => localRefetch(options)), [localRefetch]);
  const selectedTripId = useSelectedTripStore((state) => state.tripId);
  const selectStoredTrip = useSelectedTripStore((state) => state.selectTrip);
  const clearStoredTrip = useSelectedTripStore((state) => state.clear);
  const trips = useMemo(() => query.data?.trips ?? [], [query.data?.trips]);
  const hasTripData = query.data !== undefined;
  const selectionResolutionKey = accountKey && hasTripData
    ? `${accountKey}:${trips.map((trip) => trip.id).join(',')}`
    : null;
  const [resolvedSelectionKey, setResolvedSelectionKey] = useState<string | null>(null);
  const selectionResolved = selectionResolutionKey !== null
    && resolvedSelectionKey === selectionResolutionKey;

  const selectTrip = useCallback((tripId: string) => {
    const trip = trips.find((item) => item.id === tripId);
    if (!trip) return;
    selectStoredTrip(trip.id);
    if (principalType === 'passenger') {
      void rememberPassengerTrip(trips, trip.id).catch(() => undefined);
    }
  }, [principalType, selectStoredTrip, trips]);

  useEffect(() => {
    if (!hasTripData || !selectionResolutionKey) return;
    const markResolved = () => setResolvedSelectionKey(selectionResolutionKey);
    if (!trips.length) {
      if (selectedTripId) clearStoredTrip();
      markResolved();
      return;
    }
    if (trips.some((trip) => trip.id === selectedTripId)) {
      markResolved();
      return;
    }
    if (principalType !== 'passenger') {
      const first = trips[0];
      if (first) selectStoredTrip(first.id);
      markResolved();
      return;
    }

    let active = true;
    void rememberedPassengerTrip(trips).then(async (remembered) => {
      if (!active) return;
      if (remembered) {
        selectStoredTrip(remembered.id);
        markResolved();
        return;
      }
      if (trips.length === 1 && trips[0]) {
        await rememberPassengerTrip(trips, trips[0].id);
        if (active) {
          selectStoredTrip(trips[0].id);
          markResolved();
        }
        return;
      }
      clearStoredTrip();
      markResolved();
    }).catch(() => {
      if (active) {
        if (trips.length > 1) clearStoredTrip();
        markResolved();
      }
    });
    return () => {
      active = false;
    };
  }, [clearStoredTrip, hasTripData, principalType, selectStoredTrip, selectedTripId, selectionResolutionKey, trips]);

  return {
    ...query,
    refetch: coordinatedRefetch,
    trips,
    offline: query.data?.offline ?? false,
    selectedTripId,
    selectedTrip: query.data?.trips.find((trip) => trip.id === selectedTripId) ?? null,
    selectionResolved,
    selectTrip,
  };
}

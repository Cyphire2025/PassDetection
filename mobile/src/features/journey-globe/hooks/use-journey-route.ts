import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useMemo } from 'react';

import { apiRequest } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';
import { isDemoMode } from '@/core/demo/demo-mode';
import { withAccountQueryContext } from '@/core/query/account-query-context';
import type { Trip } from '@/features/trips/model/trip';

import { JourneyDestinationSchema, routeFromLookup, type JourneyLookupStatus } from '../model/journey-destination';
import { resolveJourneyRoute } from '../model/journey-route';

const journeyDestinationQueryKey = (accountKey: string | null, tripId: string, destination: string | null) => (
  ['journey-destination', accountKey, tripId, destination] as const
);

/** Refresh the card's lookup without creating another remote-query observer. */
export function useJourneyRouteRefresh(trip: Trip | null) {
  const client = useQueryClient();
  const principal = useSessionStore((state) => state.session?.principal);
  const accountKey = principal ? principalAccountNamespace(principal) : null;
  const tripId = trip?.id;
  const destination = trip?.destination;
  const demo = isDemoMode();
  return useCallback(async () => {
    if (!accountKey || !tripId || !destination || demo) return;
    // Inactive cards become stale and refresh when visible again. A visible
    // card retries even a recent ambiguous result after an explicit refresh.
    await client.invalidateQueries({
      queryKey: journeyDestinationQueryKey(accountKey, tripId, destination),
      exact: true,
      refetchType: 'active',
    });
  }, [accountKey, client, demo, destination, tripId]);
}

export function useJourneyRoute(trip: Trip, active: boolean) {
  const principal = useSessionStore((state) => state.session?.principal);
  const accountKey = principal ? principalAccountNamespace(principal) : null;
  const demo = isDemoMode();
  const query = useQuery({
    // Including the destination prevents a finalized group's changed destination
    // from reusing the old marker. Account isolation matches other trip queries.
    queryKey: journeyDestinationQueryKey(accountKey, trip.id, trip.destination),
    queryFn: ({ signal }) => withAccountQueryContext(signal, (context) => apiRequest(
      `/mobile/trips/${encodeURIComponent(trip.id)}/journey-destination`,
      { schema: JourneyDestinationSchema, signal: context.signal, timeoutMs: 12_000 },
    )),
    enabled: Boolean(active && accountKey && trip.destination && !demo),
    staleTime: (state) => state.state.data?.status === 'resolved' ? 24 * 60 * 60 * 1_000 : 30_000,
    gcTime: 24 * 60 * 60 * 1_000,
    retry: false,
    refetchOnReconnect: true,
    // Concurrent first lookups can wait behind the shared provider admission.
    // Retry a temporary response at most twice, respecting its backoff.
    refetchInterval: (state) => active && state.state.data?.status === 'unavailable'
      && state.state.dataUpdateCount < 3
      ? Math.max(5_000, (state.state.data.retry_after_seconds ?? 30) * 1_000) : false,
  });
  const route = useMemo(() => demo
    ? resolveJourneyRoute(trip)
    : query.data ? routeFromLookup(trip.id, query.data) : null,
  [demo, query.data, trip]);
  const status: JourneyLookupStatus = demo ? (route ? 'resolved' : 'not_found')
    : query.data?.status ?? (query.isError ? 'unavailable' : 'resolving');
  return { route, status };
}

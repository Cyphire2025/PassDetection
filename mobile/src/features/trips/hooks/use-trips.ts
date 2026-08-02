import { useQuery } from '@tanstack/react-query';
import { useEffect } from 'react';

import { useSessionStore } from '@/core/auth/session-store';

import { refreshTrips } from '../data/trip-repository';
import { useSelectedTripStore } from '../state/selected-trip-store';

export function useTrips() {
  const principalId = useSessionStore((state) => state.session?.principal.id);
  const query = useQuery({
    queryKey: ['mobile-trips', principalId],
    queryFn: refreshTrips,
    enabled: Boolean(principalId),
  });
  const selectedTripId = useSelectedTripStore((state) => state.tripId);
  const selectTrip = useSelectedTripStore((state) => state.selectTrip);

  useEffect(() => {
    const trips = query.data?.trips ?? [];
    if (trips.length > 0 && !trips.some((trip) => trip.id === selectedTripId)) {
      const first = trips[0];
      if (first) selectTrip(first.id);
    }
  }, [query.data?.trips, selectTrip, selectedTripId]);

  return {
    ...query,
    trips: query.data?.trips ?? [],
    offline: query.data?.offline ?? false,
    selectedTripId,
    selectedTrip: query.data?.trips.find((trip) => trip.id === selectedTripId) ?? null,
    selectTrip,
  };
}

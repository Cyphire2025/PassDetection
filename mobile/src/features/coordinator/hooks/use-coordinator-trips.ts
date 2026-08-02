import { useQuery } from '@tanstack/react-query';
import { useCallback, useEffect } from 'react';

import { useSessionStore } from '@/core/auth/session-store';
import { refreshTrips } from '@/features/trips/data/trip-repository';

import { useCoordinatorTripStore } from '../state/coordinator-trip-store';

export function useCoordinatorTrips() {
  const principal = useSessionStore((state) => state.session?.principal ?? null);
  const principalId = principal?.principalType === 'coordinator' ? principal.id : null;
  const storedPrincipalId = useCoordinatorTripStore((state) => state.principalId);
  const storedTripId = useCoordinatorTripStore((state) => state.tripId);
  const activatePrincipal = useCoordinatorTripStore((state) => state.activatePrincipal);
  const selectStoredTrip = useCoordinatorTripStore((state) => state.selectTrip);
  const clearStoredSelection = useCoordinatorTripStore((state) => state.clearSelection);

  const query = useQuery({
    queryKey: ['mobile-trips', principalId],
    queryFn: refreshTrips,
    enabled: Boolean(principalId),
    staleTime: 15_000,
    refetchOnMount: 'always',
  });
  const selectedTripId = storedPrincipalId === principalId ? storedTripId : null;

  useEffect(() => {
    activatePrincipal(principalId);
  }, [activatePrincipal, principalId]);

  useEffect(() => {
    if (!principalId || !selectedTripId || !query.data) return;
    if (!query.data.trips.some((trip) => trip.id === selectedTripId)) {
      clearStoredSelection(principalId);
    }
  }, [clearStoredSelection, principalId, query.data, selectedTripId]);

  const selectTrip = useCallback((tripId: string) => {
    if (principalId) selectStoredTrip(principalId, tripId);
  }, [principalId, selectStoredTrip]);

  const clearSelection = useCallback(() => {
    if (principalId) clearStoredSelection(principalId);
  }, [clearStoredSelection, principalId]);

  const trips = query.data?.trips ?? [];
  return {
    ...query,
    trips,
    offline: query.data?.offline ?? false,
    selectedTripId,
    selectedTrip: trips.find((trip) => trip.id === selectedTripId) ?? null,
    selectTrip,
    clearSelection,
  };
}

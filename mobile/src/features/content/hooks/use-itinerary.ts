import { useQuery } from '@tanstack/react-query';

import { refreshItinerary } from '../data/itinerary-repository';

export function useItinerary(tripId: string | null) {
  return useQuery({
    queryKey: ['trip-itinerary', tripId],
    queryFn: () => refreshItinerary(tripId!),
    enabled: Boolean(tripId),
  });
}

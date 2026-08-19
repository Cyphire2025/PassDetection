import type { ImmutableSyncContext } from '@/core/sync/sync-context';

import { loadLocalItinerary } from '../data/itinerary-repository';
import { useCacheFirstTripQuery } from './use-content';

const cachedItinerary = async (tripId: string, context?: ImmutableSyncContext) => {
  const itinerary = await loadLocalItinerary(tripId, context);
  return itinerary ? { itinerary, offline: true as const } : null;
};

export function useItinerary(tripId: string | null) {
  return useCacheFirstTripQuery({
    keyPrefix: 'trip-itinerary',
    tripId,
    cached: cachedItinerary,
  });
}

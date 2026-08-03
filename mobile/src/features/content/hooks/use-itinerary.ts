import { loadLocalItinerary, refreshItinerary } from '../data/itinerary-repository';
import { useCacheFirstTripQuery } from './use-content';

const cachedItinerary = async (tripId: string) => {
  const itinerary = await loadLocalItinerary(tripId);
  return itinerary ? { itinerary, offline: true as const } : null;
};

export function useItinerary(tripId: string | null) {
  return useCacheFirstTripQuery({
    keyPrefix: 'trip-itinerary',
    tripId,
    refresh: refreshItinerary,
    cached: cachedItinerary,
  });
}

import { z } from 'zod';

import { routeToDestination } from './journey-route';

export const JourneyDestinationSchema = z.object({
  status: z.enum(['resolved', 'unavailable', 'ambiguous', 'not_found', 'not_configured']),
  destination: z.object({
    label: z.string().min(1).max(255),
    country: z.string().min(1).max(160),
    country_code: z.string().min(2).max(3),
    latitude: z.number().finite().min(-90).max(90),
    longitude: z.number().finite().min(-180).max(180),
    place_type: z.enum(['city', 'state', 'country', 'region']),
  }).nullable(),
  attribution: z.string().max(150),
  attribution_url: z.literal('https://www.openstreetmap.org/copyright'),
  retry_after_seconds: z.number().nonnegative().nullable().optional(),
});
export type JourneyDestination = z.infer<typeof JourneyDestinationSchema>;
export type JourneyLookupStatus = JourneyDestination['status'] | 'resolving';

export function routeFromLookup(tripId: string, lookup: JourneyDestination) {
  if (lookup.status !== 'resolved' || !lookup.destination) return null;
  const place = lookup.destination;
  return routeToDestination(tripId, {
    city: place.label, country: place.country, countryCode: place.country_code.toUpperCase(),
    latitude: place.latitude, longitude: place.longitude, placeType: place.place_type,
  }, lookup.attribution);
}

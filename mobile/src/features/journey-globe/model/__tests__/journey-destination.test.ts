import { JourneyDestinationSchema, routeFromLookup } from '../journey-destination';

const lookup = {
  status: 'resolved' as const,
  destination: { label: 'Kerala', country: 'India', country_code: 'in', latitude: 10.35, longitude: 76.51, place_type: 'state' as const },
  attribution: '© OpenStreetMap contributors', attribution_url: 'https://www.openstreetmap.org/copyright' as const,
};

test('preserves a geocoded state without substituting an airport or city', () => {
  const route = routeFromLookup('kerala-trip', JourneyDestinationSchema.parse(lookup))!;
  expect(route.origin.city).toBe('New Delhi');
  expect(route.destination).toMatchObject({ city: 'Kerala', countryCode: 'IN', placeType: 'state', latitude: 10.35 });
  expect(route.destination.iata).toBeUndefined();
  expect(route.distanceKm).toBeGreaterThan(1_000);
  expect(route.attribution).toBe(lookup.attribution);
});

test('route identity changes with group and resolved coordinates', () => {
  const first = routeFromLookup('one', lookup)!;
  expect(routeFromLookup('two', lookup)!.key).not.toBe(first.key);
  expect(routeFromLookup('one', { ...lookup, destination: { ...lookup.destination, latitude: 11 } })!.key).not.toBe(first.key);
});

test.each(['unavailable', 'ambiguous', 'not_found', 'not_configured'] as const)('does not draw an endpoint for %s', (status) => {
  expect(routeFromLookup('one', { ...lookup, status })).toBeNull();
});

test.each([NaN, Infinity, -91, 91])('rejects invalid latitude %s at the API boundary', (latitude) => {
  expect(JourneyDestinationSchema.safeParse({ ...lookup, destination: { ...lookup.destination, latitude } }).success).toBe(false);
});

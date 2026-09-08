import { DESTINATION_CATALOG } from '../destination-catalog';
import { resolveJourneyRoute } from '../journey-route';

const trip = (destination: string | null, id = 'trip-one', name = 'Group title') => ({
  id, destination, name,
});

describe('group destination illustrations', () => {
  it.each([
    ['Australia', 'Sydney', 'AU'],
    ['Dubai', 'Dubai', 'AE'],
    ['UAE', 'Dubai', 'AE'],
    ['United Arab Emirates (UAE)', 'Dubai', 'AE'],
    ['Singapore', 'Singapore', 'SG'],
    ['Dubai, UAE', 'Dubai', 'AE'],
    ['  Melbourne, Australia  ', 'Melbourne', 'AU'],
    ['Australia / Melbourne', 'Melbourne', 'AU'],
    ['Bali, Indonesia', 'Denpasar', 'ID'],
    ['Sydney (SYD), Australia', 'Sydney', 'AU'],
    ['SYD', 'Sydney', 'AU'],
    ['dxb', 'Dubai', 'AE'],
    ['AU', 'Sydney', 'AU'],
    ['AUS', 'Sydney', 'AU'],
    ['USA', 'New York', 'US'],
    ['US', 'New York', 'US'],
    ['Zürich, Switzerland', 'Zurich', 'CH'],
    ['São Paulo', 'São Paulo', 'BR'],
    ['Male', 'Malé', 'MV'],
    ['Türkiye', 'Istanbul', 'TR'],
  ])('maps %s to its explicitly supported place', (destination, city, countryCode) => {
    const route = resolveJourneyRoute(trip(destination));
    expect(route).toMatchObject({
      kind: 'illustrative',
      origin: { city: 'New Delhi', countryCode: 'IN', iata: 'DEL' },
      destination: { city, countryCode },
    });
    expect(route!.distanceKm).toBeGreaterThan(0);
  });

  it.each([
    null, '', '   ', 'Atlantis', 'Paris Texas', 'Paris, Texas',
    'Dubai and Singapore', 'Singapore / Malaysia', 'Sydney & Melbourne',
    'Australia / New Zealand', 'Paris, Germany', 'Fly us somewhere',
    'Australia surprise retreat', 'FRA', 'Delhi', 'DEL', 'India',
  ])('does not invent a route for %s', (destination) => {
    expect(resolveJourneyRoute(trip(destination, 'trip-one', 'Singapore Discovery'))).toBeNull();
  });

  it('keeps the same semantic destination stable across label variants', () => {
    expect(resolveJourneyRoute(trip('Dubai'))?.key)
      .toBe(resolveJourneyRoute(trip('DXB'))?.key);
  });

  it('changes the route identity on group or destination changes', () => {
    const original = resolveJourneyRoute(trip('Australia', 'one'))!;
    expect(resolveJourneyRoute(trip('Australia', 'two'))!.key).not.toBe(original.key);
    expect(resolveJourneyRoute(trip('Dubai', 'one'))!.key).not.toBe(original.key);
    expect(resolveJourneyRoute(trip('Unknown', 'one'))).toBeNull();
  });

  it('does not use the display name as geographic data', () => {
    expect(resolveJourneyRoute(trip(null, 'one', 'Dubai Tour'))).toBeNull();
    expect(resolveJourneyRoute(trip('Singapore', 'one', 'Australia Tour'))!.destination.city)
      .toBe('Singapore');
  });

  it('uses approximate great-circle distance, not a flight itinerary distance', () => {
    const route = resolveJourneyRoute(trip('Dubai'))!;
    expect(route.distanceKm).toBeGreaterThan(2_100);
    expect(route.distanceKm).toBeLessThan(2_300);
    expect(route.kind).toBe('illustrative');
  });

  it('does not allow a caller to mutate future route coordinates', () => {
    const route = resolveJourneyRoute(trip('Dubai'))!;
    route.origin.latitude = 0;
    route.destination.longitude = 0;
    const again = resolveJourneyRoute(trip('Dubai'))!;
    expect(again.origin.latitude).not.toBe(0);
    expect(again.destination.longitude).not.toBe(0);
  });

  it('keeps bundled geographic coordinates finite and in bounds', () => {
    for (const { point } of DESTINATION_CATALOG) {
      expect(Number.isFinite(point.latitude)).toBe(true);
      expect(Number.isFinite(point.longitude)).toBe(true);
      expect(Math.abs(point.latitude)).toBeLessThanOrEqual(90);
      expect(Math.abs(point.longitude)).toBeLessThanOrEqual(180);
      expect(point.countryCode).toMatch(/^[A-Z]{2}$/);
      expect(point.iata).toMatch(/^[A-Z]{3}$/);
    }
  });
});

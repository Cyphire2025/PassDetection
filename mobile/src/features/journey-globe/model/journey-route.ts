import type { Trip } from '@/features/trips/model/trip';

import { DESTINATION_CATALOG } from './destination-catalog';

export type GeoPoint = {
  city: string;
  country: string;
  countryCode: string;
  latitude: number;
  longitude: number;
  iata?: string;
  placeType?: 'city' | 'state' | 'country' | 'region';
};

export type JourneyRoute = {
  key: string;
  origin: GeoPoint;
  destination: GeoPoint;
  kind: 'illustrative' | 'flight';
  distanceKm: number;
  attribution?: string;
};

/**
 * Destination illustration policy v1:
 * - Only the group's destination field supplies a destination; names are not evidence.
 * - Complete city, country or airport-code aliases must match. Extra unknown words
 *   and multiple destinations are not silently discarded.
 * - A city with its own country qualifier wins over that country's representative
 *   hub. Country-only examples: Australia -> Sydney, UAE -> Dubai, India -> Delhi.
 * - New Delhi is the illustrative origin. This adapter has no booking/flight feed
 *   and never emits kind=flight. Airport coordinates do not imply a booked airport.
 */
export const JOURNEY_ROUTE_MAPPING_POLICY = 'group-destination-delhi-illustration-v1';

function normalizePlace(value: string): string {
  return value.normalize('NFKD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()
    .replace(/[.'’]/g, '')
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

const aliases = new Map<string, Set<GeoPoint>>();

function addAlias(value: string, point: GeoPoint): void {
  const normalized = normalizePlace(value);
  if (!normalized) return;
  const matches = aliases.get(normalized) ?? new Set<GeoPoint>();
  matches.add(point);
  aliases.set(normalized, matches);
}

for (const entry of DESTINATION_CATALOG) {
  const { point } = entry;
  const countryDefault = DESTINATION_CATALOG.find((candidate) => (
    candidate.point.countryCode === point.countryCode && candidate.countryAliases.length > 0
  ));
  const qualifiers = new Set([
    point.country, point.countryCode, ...(countryDefault?.countryAliases ?? []),
  ]);
  const names = new Set([point.city, ...(point.iata ? [point.iata] : []), ...entry.aliases]);
  for (const name of names) {
    addAlias(name, point);
    for (const qualifier of qualifiers) {
      addAlias(`${name} ${qualifier}`, point);
      addAlias(`${qualifier} ${name}`, point);
      if (point.iata && name !== point.iata) {
        addAlias(`${name} ${point.iata} ${qualifier}`, point);
      }
    }
    if (point.iata && name !== point.iata) {
      addAlias(`${name} ${point.iata}`, point);
      addAlias(`${point.iata} ${name}`, point);
    }
  }
  for (const countryAlias of entry.countryAliases) addAlias(countryAlias, point);
}

const origin = DESTINATION_CATALOG.find((entry) => entry.point.iata === 'DEL')!.point;
const EARTH_MEAN_RADIUS_KM = 6_371.0088;

/** The geocoder supplies a geographic destination, never a booked airport. */
export function routeToDestination(tripId: string, destination: GeoPoint, attribution?: string): JourneyRoute | null {
  if (!Number.isFinite(destination.latitude) || !Number.isFinite(destination.longitude)
    || Math.abs(destination.latitude) > 90 || Math.abs(destination.longitude) > 180) return null;
  const distanceKm = distanceBetween(origin, destination);
  if (distanceKm < 1) return null;
  return {
    key: `group-geographic-destination-v2:${tripId}:${destination.city}:${destination.latitude}:${destination.longitude}`,
    origin: { ...origin }, destination: { ...destination }, kind: 'illustrative', distanceKm,
    ...(attribution ? { attribution } : {}),
  };
}

function distanceBetween(start: GeoPoint, end: GeoPoint): number {
  const radians = Math.PI / 180;
  const latitudeDelta = (end.latitude - start.latitude) * radians;
  const longitudeDelta = (end.longitude - start.longitude) * radians;
  const haversine = Math.sin(latitudeDelta / 2) ** 2
    + Math.cos(start.latitude * radians) * Math.cos(end.latitude * radians)
    * Math.sin(longitudeDelta / 2) ** 2;
  return Math.round(2 * EARTH_MEAN_RADIUS_KM * Math.asin(Math.sqrt(Math.min(1, haversine))));
}

export function resolveJourneyRoute(
  trip: Pick<Trip, 'id' | 'destination' | 'name'>,
): JourneyRoute | null {
  if (!trip.destination) return null;
  const matches = aliases.get(normalizePlace(trip.destination));
  if (!matches || matches.size !== 1) return null;
  const destination = matches.values().next().value;
  if (!destination) return null;
  const distanceKm = distanceBetween(origin, destination);
  if (distanceKm < 1) return null;
  return {
    key: `${JOURNEY_ROUTE_MAPPING_POLICY}:${trip.id}:${origin.countryCode}:${origin.iata}:${destination.countryCode}:${destination.iata}`,
    origin: { ...origin },
    destination: { ...destination },
    kind: 'illustrative',
    distanceKm,
  };
}

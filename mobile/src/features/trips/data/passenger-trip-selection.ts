import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';
import { getRememberedTripId, setRememberedTripId } from '@/core/storage/secure-store';

import type { Trip } from '../model/trip';

export type PassengerTripDestination =
  | '/(passenger)/(tabs)/trip'
  | '/(passenger)/(tabs)/documents'
  | '/(passenger)/(tabs)/qr'
  | '/(passenger)/(tabs)/updates';

function passengerNamespace(): string {
  const principal = useSessionStore.getState().session?.principal;
  if (!principal || principal.principalType !== 'passenger') {
    throw new Error('Passenger authentication is required to select a trip.');
  }
  return principalAccountNamespace(principal);
}

export function eligiblePassengerTrip(trips: readonly Trip[], tripId: string | null): Trip | null {
  if (!tripId) return null;
  return trips.find((trip) => trip.role === 'passenger' && trip.id === tripId) ?? null;
}

export function passengerTripForRequiredPreload(
  trips: readonly Trip[],
  requestedTripId?: string,
): Trip | null {
  if (requestedTripId) return eligiblePassengerTrip(trips, requestedTripId);
  const passengerTrips = trips.filter((trip) => trip.role === 'passenger');
  return passengerTrips.length === 1 ? passengerTrips[0] ?? null : null;
}

export async function rememberedPassengerTrip(trips: readonly Trip[]): Promise<Trip | null> {
  return eligiblePassengerTrip(trips, await getRememberedTripId(passengerNamespace()));
}

export async function rememberPassengerTrip(trips: readonly Trip[], tripId: string): Promise<Trip> {
  const trip = eligiblePassengerTrip(trips, tripId);
  if (!trip) throw new Error('This trip is not assigned to the current passenger account.');
  await setRememberedTripId(passengerNamespace(), trip.id);
  return trip;
}

export function passengerTripDestination(route: string | null | undefined): PassengerTripDestination {
  switch (route) {
    case 'documents':
      return '/(passenger)/(tabs)/documents';
    case 'qr':
      return '/(passenger)/(tabs)/qr';
    case 'updates':
      return '/(passenger)/(tabs)/updates';
    default:
      return '/(passenger)/(tabs)/trip';
  }
}

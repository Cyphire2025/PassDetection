import { principalAccountNamespace, type MobilePrincipal, type MobileRole } from '@/core/auth/types';
import type { Trip } from '@/features/trips/model/trip';

import type { NotificationData } from './notification-service';

export type NotificationDestination =
  | '/(passenger)/select-trip'
  | '/(manager)/(tabs)/groups'
  | '/(manager)/(tabs)/itinerary'
  | '/(manager)/(tabs)/readiness'
  | '/(manager)/(tabs)/updates'
  | '/(coordinator)/(tabs)/groups'
  | '/(coordinator)/(tabs)/attendance'
  | '/(coordinator)/(tabs)/passengers'
  | '/(coordinator)/operations/updates';

export function notificationAccountKey(
  principal: Pick<MobilePrincipal, 'agencyId' | 'accountId'>,
): string {
  return principalAccountNamespace(principal);
}

export function notificationDestination(
  role: MobileRole,
  route: NotificationData['route'],
): NotificationDestination {
  if (role === 'passenger') return '/(passenger)/select-trip';
  if (role === 'client_manager') {
    if (route === 'readiness') return '/(manager)/(tabs)/readiness';
    if (route === 'updates') return '/(manager)/(tabs)/updates';
    if (route === 'trip' || route === 'documents') return '/(manager)/(tabs)/itinerary';
    return '/(manager)/(tabs)/groups';
  }
  if (route === 'attendance') return '/(coordinator)/(tabs)/attendance';
  if (route === 'passengers') return '/(coordinator)/(tabs)/passengers';
  if (route === 'updates') return '/(coordinator)/operations/updates';
  return '/(coordinator)/(tabs)/groups';
}

export function notificationResponseKey(
  data: NotificationData,
  requestIdentifier: string,
): string | null {
  if (data.event_id) return `event:${data.event_id}`;
  const normalized = requestIdentifier.trim();
  return normalized && normalized.length <= 240 ? `request:${normalized}` : null;
}

export function isAssignedNotificationTrip(
  trips: readonly Pick<Trip, 'id'>[],
  tripId: string,
): boolean {
  return trips.some((trip) => trip.id === tripId);
}

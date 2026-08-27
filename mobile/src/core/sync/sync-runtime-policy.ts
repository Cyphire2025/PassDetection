import type { Trip } from '@/features/trips/model/trip';

export const SELECTED_TRIP_FALLBACK_INTERVAL_MS = 5 * 60_000;
export const FULL_TRIP_RECONCILIATION_INTERVAL_MS = 30 * 60_000;

export type SyncScope = 'none' | 'selected' | 'full';

const LOCAL_SYNC_PROJECTION_PREFIXES = new Set([
  'coordinator-attendance-roster',
  'coordinator-attendance-sessions',
  'coordinator-roster',
  'manager-attendance-roster',
  'manager-attendance-sessions',
  'manager-readiness',
  'mobile-trips',
  'my-photos-summary',
  'trip-announcements',
  'trip-common-documents',
  'trip-documents',
  'trip-itinerary',
  'trip-meal',
  'trip-qr',
  'trip-room',
]);

export function syncRuntimeTimestamp(): number {
  return Date.now();
}

export function resolveSyncScope(input: {
  forceFull: boolean;
  selectedTripId: string | null;
  lastFullSyncAt: number | null;
  now: number;
}): SyncScope {
  const fullSyncDue = input.lastFullSyncAt === null
    || input.lastFullSyncAt > input.now
    || input.now - input.lastFullSyncAt >= FULL_TRIP_RECONCILIATION_INTERVAL_MS;
  if (input.forceFull || fullSyncDue) return 'full';
  return input.selectedTripId ? 'selected' : 'none';
}

export function mergeSyncScopes(current: SyncScope, requested: SyncScope): SyncScope {
  if (current === 'full' || requested === 'full') return 'full';
  if (current === 'selected' || requested === 'selected') return 'selected';
  return 'none';
}

export function changedSyncTripIds(
  results: { tripId: string; changed: boolean }[],
): string[] {
  return [...new Set(results.filter((result) => result.changed).map((result) => result.tripId))];
}

export function queryKeyMatchesAnyTrip(
  queryKey: readonly unknown[],
  tripIds: readonly string[],
): boolean {
  return tripIds.some((tripId) => queryKey.includes(tripId));
}

export function isLocalSyncProjectionQuery(queryKey: readonly unknown[]): boolean {
  const prefix = queryKey[0];
  return typeof prefix === 'string' && LOCAL_SYNC_PROJECTION_PREFIXES.has(prefix);
}

export function queryKeyMatchesChangedProjection(
  queryKey: readonly unknown[],
  tripIds: readonly string[],
): boolean {
  return isLocalSyncProjectionQuery(queryKey) && queryKeyMatchesAnyTrip(queryKey, tripIds);
}

const comparableTrip = (trip: Trip) => ({
  id: trip.id,
  name: trip.name,
  destination: trip.destination,
  travelDate: trip.travelDate,
  returnDate: trip.returnDate,
  role: trip.role,
  accessGeneration: trip.accessGeneration,
  itineraryVersion: trip.itineraryVersion,
  commonDocumentVersion: trip.commonDocumentVersion,
  announcementVersion: trip.announcementVersion,
});

export function tripCollectionsDiffer(previous: Trip[], next: Trip[]): boolean {
  const stable = (trips: Trip[]) => trips
    .map(comparableTrip)
    .sort((left, right) => left.id.localeCompare(right.id));
  return JSON.stringify(stable(previous)) !== JSON.stringify(stable(next));
}

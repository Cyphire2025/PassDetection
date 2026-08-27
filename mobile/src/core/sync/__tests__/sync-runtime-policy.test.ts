import type { Trip } from '@/features/trips/model/trip';
import { DEFAULT_TRIP_TIME_ZONE } from '@/core/localization/time-zone';

import {
  FULL_TRIP_RECONCILIATION_INTERVAL_MS,
  SELECTED_TRIP_FALLBACK_INTERVAL_MS,
  changedSyncTripIds,
  mergeSyncScopes,
  isLocalSyncProjectionQuery,
  queryKeyMatchesChangedProjection,
  queryKeyMatchesAnyTrip,
  resolveSyncScope,
  tripCollectionsDiffer,
} from '../sync-runtime-policy';

const trip = (overrides: Partial<Trip> = {}): Trip => ({
  id: '8cb51225-5543-4204-bbea-06bebffc35ad',
  name: 'Vietnam 2026',
  destination: 'Vietnam',
  travelDate: '2026-08-12',
  returnDate: '2026-08-15',
  timeZone: DEFAULT_TRIP_TIME_ZONE,
  role: 'coordinator',
  accessGeneration: 1,
  accessExpiresAt: null,
  itineraryVersion: 1,
  commonDocumentVersion: 1,
  announcementVersion: 1,
  updatedAt: '2026-08-03T09:00:00+00:00',
  ...overrides,
});

test('foreground fallback is at least twenty times slower than the removed 15 second loop', () => {
  expect(SELECTED_TRIP_FALLBACK_INTERVAL_MS).toBeGreaterThanOrEqual(20 * 15_000);
  expect(FULL_TRIP_RECONCILIATION_INTERVAL_MS).toBeGreaterThanOrEqual(
    6 * SELECTED_TRIP_FALLBACK_INTERVAL_MS,
  );
});

test('selects one trip until the periodic full reconciliation is due', () => {
  expect(resolveSyncScope({
    forceFull: false,
    selectedTripId: trip().id,
    lastFullSyncAt: 1_000,
    now: 1_000 + SELECTED_TRIP_FALLBACK_INTERVAL_MS,
  })).toBe('selected');
  expect(resolveSyncScope({
    forceFull: false,
    selectedTripId: trip().id,
    lastFullSyncAt: 1_000,
    now: 1_000 + FULL_TRIP_RECONCILIATION_INTERVAL_MS,
  })).toBe('full');
  expect(resolveSyncScope({
    forceFull: false,
    selectedTripId: null,
    lastFullSyncAt: 1_000,
    now: 1_000 + SELECTED_TRIP_FALLBACK_INTERVAL_MS,
  })).toBe('none');
  expect(resolveSyncScope({
    forceFull: false,
    selectedTripId: trip().id,
    lastFullSyncAt: 2_000,
    now: 1_000,
  })).toBe('full');
});

test('publication matches only synchronized local projections', () => {
  expect(isLocalSyncProjectionQuery(['trip-itinerary', 'trip-a', 'account-a'])).toBe(true);
  expect(queryKeyMatchesChangedProjection(
    ['coordinator-roster', 'account-a', 'trip-a', '', 'all'],
    ['trip-a'],
  )).toBe(true);
  expect(queryKeyMatchesChangedProjection(
    ['mobile-notifications', 'trip-a', 'account-a'],
    ['trip-a'],
  )).toBe(false);
  expect(queryKeyMatchesChangedProjection(
    ['manager-attendance-sessions', 'account-a', 'trip-a'],
    ['trip-a'],
  )).toBe(true);
  expect(queryKeyMatchesChangedProjection(
    ['coordinator-attendance-roster', 'account-a', 'trip-a', 'session-a', 'missing'],
    ['trip-a'],
  )).toBe(true);
});

test('full synchronization wins when event triggers are coalesced', () => {
  expect(mergeSyncScopes('selected', 'full')).toBe('full');
  expect(mergeSyncScopes('none', 'selected')).toBe('selected');
  expect(mergeSyncScopes('selected', 'selected')).toBe('selected');
});

test('scoped invalidation selects only queries for trips that actually changed', () => {
  const changed = changedSyncTripIds([
    { tripId: 'trip-a', changed: false },
    { tripId: 'trip-b', changed: true },
    { tripId: 'trip-b', changed: true },
  ]);
  expect(changed).toEqual(['trip-b']);
  expect(queryKeyMatchesAnyTrip(['trip-common-documents', 'trip-b'], changed)).toBe(true);
  expect(queryKeyMatchesAnyTrip(['trip-common-documents', 'trip-a'], changed)).toBe(false);
  expect(queryKeyMatchesAnyTrip(['unrelated-dashboard-query'], changed)).toBe(false);
});

test('trip reconciliation ignores cache timestamps but detects authoritative changes', () => {
  expect(tripCollectionsDiffer(
    [trip()],
    [trip({ updatedAt: '2026-08-03T10:00:00+00:00' })],
  )).toBe(false);
  expect(tripCollectionsDiffer([trip()], [trip({ name: 'Vietnam Updated' })])).toBe(true);
  expect(tripCollectionsDiffer([trip()], [])).toBe(true);
});

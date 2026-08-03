import { TripListSchema } from '@/core/api/contracts';
import { apiRequest, ApiError } from '@/core/api/client';
import { principalAccountNamespace } from '@/core/auth/types';
import { useSessionStore } from '@/core/auth/session-store';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';
import {
  purgeTripCache,
  retryPendingTripPurges,
  TripVaultPurgePendingError,
} from '@/core/sync/access-cache';
import { isAccessLeaseExpired } from '@/core/sync/access-expiry-policy';
import {
  assertSyncContextActive,
  captureSyncContext,
  type ImmutableSyncContext,
} from '@/core/sync/sync-context';
import type { z } from 'zod';

import type { Trip } from '../model/trip';
import { collectCursorPages } from './pagination';

const TRIP_PAGE_SIZE = 100;
const MAX_TRIP_PAGES = 20;
type TripRefreshResult = { trips: Trip[]; offline: boolean };

// Trip discovery is shared by preload, runtime sync, notifications and manual
// refresh. Coalesce by the immutable authenticated session rather than by a
// mutable global so callers cannot race duplicate pagination/store jobs.
const tripRefreshInFlight = new Map<string, Promise<TripRefreshResult>>();

function tripRefreshKey(syncContext: ImmutableSyncContext): string {
  // The encrypted namespace and device session stay stable across an authorized
  // passenger trip-token switch, while principalId changes to the selected
  // passenger identity. Do not let the new identity inherit the old request.
  return `${syncContext.namespace}:${syncContext.sessionId}:${syncContext.principalId}`;
}

function canUseOfflineTripFallback(error: unknown): boolean {
  if (error instanceof ApiError) {
    return error.status === 408 || error.status === 425 || error.status === 429 || error.status >= 500;
  }
  return error instanceof TypeError || (
    error instanceof Error && (error.name === 'AbortError' || error.name === 'TimeoutError')
  );
}

function activeAccount(syncContext?: ImmutableSyncContext): { namespace: string; agencyId: string } {
  if (syncContext) {
    assertSyncContextActive(syncContext);
    return { namespace: syncContext.namespace, agencyId: syncContext.agencyId };
  }
  const principal = useSessionStore.getState().session?.principal;
  if (!principal) throw new Error('Authentication is required.');
  return {
    namespace: principalAccountNamespace(principal),
    agencyId: principal.agencyId,
  };
}

async function localTripsForAccount(syncContext?: ImmutableSyncContext): Promise<Trip[]> {
  const { namespace } = activeAccount(syncContext);
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  const rows = await database.getAllAsync<{
    id: string;
    name: string;
    destination: string | null;
    travel_date: string | null;
    return_date: string | null;
    role: Trip['role'];
    access_generation: number;
    access_expires_at: string | null;
    last_server_time: string | null;
    itinerary_version: number;
    common_document_version: number;
    announcement_version: number;
    updated_at: string;
  }>(
    `SELECT id, name, destination, travel_date, return_date, role, access_generation, access_expires_at,
            (SELECT MAX(cursor.last_synced_at)
               FROM sync_cursors cursor
              WHERE cursor.account_namespace = trips.account_namespace
                AND cursor.trip_id = trips.id) AS last_server_time,
            advertised_itinerary_version AS itinerary_version,
            advertised_common_document_version AS common_document_version,
            advertised_announcement_version AS announcement_version,
            updated_at
       FROM trips
      WHERE account_namespace = ?
        AND NOT EXISTS (
          SELECT 1 FROM trip_purge_tombstones purge
           WHERE purge.account_namespace = trips.account_namespace
             AND purge.trip_id = trips.id
        )
      ORDER BY COALESCE(travel_date, '9999-12-31'), name
      LIMIT 2000`,
    namespace,
  );
  const observedNow = Date.now();
  return rows.filter((row) => (
    !row.access_expires_at || !isAccessLeaseExpired({
      accessExpiresAt: row.access_expires_at,
      lastServerTime: row.last_server_time,
    }, observedNow)
  )).map((row) => ({
    id: row.id,
    name: row.name,
    destination: row.destination,
    travelDate: row.travel_date,
    returnDate: row.return_date,
    role: row.role,
    accessGeneration: row.access_generation,
    accessExpiresAt: row.access_expires_at,
    itineraryVersion: row.itinerary_version,
    commonDocumentVersion: row.common_document_version,
    announcementVersion: row.announcement_version,
    updatedAt: row.updated_at,
  }));
}

export function localTrips(): Promise<Trip[]> {
  return localTripsForAccount();
}

export function localTripsInContext(syncContext: ImmutableSyncContext): Promise<Trip[]> {
  return localTripsForAccount(syncContext);
}

async function storeTrips(trips: Trip[], syncContext?: ImmutableSyncContext): Promise<Trip[]> {
  const { namespace, agencyId } = activeAccount(syncContext);
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  await retryPendingTripPurges(syncContext);
  if (syncContext) assertSyncContextActive(syncContext);
  const existingIds = await database.getAllAsync<{ id: string }>(
    `SELECT id FROM trips
      WHERE account_namespace = ?
        AND NOT EXISTS (
          SELECT 1 FROM trip_purge_tombstones purge
           WHERE purge.account_namespace = trips.account_namespace
             AND purge.trip_id = trips.id
        )`,
    namespace,
  );
  const incoming = new Set(trips.map((trip) => trip.id));
  const removedIds = existingIds.filter((existing) => !incoming.has(existing.id)).map((existing) => existing.id);
  for (const removedId of removedIds) {
    if (syncContext) assertSyncContextActive(syncContext);
    try {
      await purgeTripCache(removedId, syncContext, 'server_removed');
    } catch (error) {
      // The durable tombstone already hid the trip and retained the failed vault
      // deletion for startup/background retry. Database failures still abort.
      if (!(error instanceof TripVaultPurgePendingError)) throw error;
    }
  }

  if (syncContext) assertSyncContextActive(syncContext);
  const pendingPurges = await database.getAllAsync<{ trip_id: string }>(
    'SELECT trip_id FROM trip_purge_tombstones WHERE account_namespace = ?',
    namespace,
  );
  const blockedTripIds = new Set(pendingPurges.map((row) => row.trip_id));
  const allowedTrips = trips.filter((trip) => !blockedTripIds.has(trip.id));

  await withAccountTransaction(database, async (transaction) => {
    for (const trip of allowedTrips) {
      if (syncContext) assertSyncContextActive(syncContext);
      await transaction.runAsync(
        `INSERT INTO trips (
           id, account_namespace, agency_id, role, name, destination, travel_date, return_date,
           access_generation, access_expires_at,
           itinerary_version, common_document_version, personal_document_version,
           announcement_version, readiness_version, roster_version, rooming_version,
           meals_version, qr_version,
           advertised_itinerary_version, advertised_common_document_version,
           advertised_announcement_version, updated_at
         ) SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, -1, -1, -1, -1, -1, -1, -1, -1, -1, ?, ?, ?, ?
            WHERE NOT EXISTS (
              SELECT 1 FROM trip_purge_tombstones purge
               WHERE purge.account_namespace = ? AND purge.trip_id = ?
            )
         ON CONFLICT(id) DO UPDATE SET
           account_namespace = excluded.account_namespace,
           agency_id = excluded.agency_id,
           role = excluded.role,
           name = excluded.name,
           destination = excluded.destination,
           travel_date = excluded.travel_date,
           return_date = excluded.return_date,
           access_generation = excluded.access_generation,
           advertised_itinerary_version = excluded.advertised_itinerary_version,
           advertised_common_document_version = excluded.advertised_common_document_version,
           advertised_announcement_version = excluded.advertised_announcement_version,
           updated_at = excluded.updated_at`,
        trip.id,
        namespace,
        agencyId,
        trip.role,
        trip.name,
        trip.destination,
        trip.travelDate,
        trip.returnDate,
        trip.accessGeneration,
        trip.accessExpiresAt,
        trip.itineraryVersion,
        trip.commonDocumentVersion,
        trip.announcementVersion,
        trip.updatedAt,
        namespace,
        trip.id,
      );
    }
  });
  return localTripsForAccount(syncContext);
}

async function refreshTripsForAccount(
  syncContext?: ImmutableSyncContext,
): Promise<TripRefreshResult> {
  let items: z.infer<typeof TripListSchema>['items'];
  try {
    if (syncContext) assertSyncContextActive(syncContext);
    items = await collectCursorPages(async (cursor) => {
      if (syncContext) assertSyncContextActive(syncContext);
      const query = new URLSearchParams({ limit: String(TRIP_PAGE_SIZE) });
      if (cursor) query.set('cursor', cursor);
      return apiRequest(`/mobile/trips?${query.toString()}`, {
        schema: TripListSchema,
        ...(syncContext ? { signal: syncContext.signal } : {}),
      });
    }, MAX_TRIP_PAGES);
  } catch (networkError) {
    if (syncContext) assertSyncContextActive(syncContext);
    // Authentication, authorization, validation and lifecycle responses are
    // authoritative. Serving stale assignments for those responses could retain
    // access after it was revoked, so only transport/server failures go offline.
    if (!canUseOfflineTripFallback(networkError)) throw networkError;
    const trips = await localTripsForAccount(syncContext);
    if (trips.length > 0) return { trips, offline: true };
    throw networkError;
  }

  if (syncContext) assertSyncContextActive(syncContext);
  const now = new Date().toISOString();
  const trips: Trip[] = items.map((item) => ({
    id: item.id,
    name: item.name,
    destination: item.destination,
    travelDate: item.travel_date,
    returnDate: item.return_date,
    role: item.role,
    accessGeneration: item.access_generation,
    accessExpiresAt: null,
    itineraryVersion: item.itinerary_version,
    commonDocumentVersion: item.common_document_version,
    announcementVersion: item.announcement_version,
    updatedAt: now,
  }));
  const storedTrips = await storeTrips(trips, syncContext);
  return { trips: storedTrips, offline: false };
}

function coalescedTripRefresh(syncContext: ImmutableSyncContext): Promise<TripRefreshResult> {
  assertSyncContextActive(syncContext);
  const key = tripRefreshKey(syncContext);
  const existing = tripRefreshInFlight.get(key);
  if (existing) return existing;

  const refresh = refreshTripsForAccount(syncContext).finally(() => {
    if (tripRefreshInFlight.get(key) === refresh) {
      tripRefreshInFlight.delete(key);
    }
  });
  tripRefreshInFlight.set(key, refresh);
  return refresh;
}

export function refreshTrips(): Promise<TripRefreshResult> {
  const lease = captureSyncContext();
  const key = tripRefreshKey(lease.context);
  const existing = tripRefreshInFlight.get(key);
  if (existing) {
    lease.release();
    return existing;
  }

  const refresh = refreshTripsForAccount(lease.context).finally(() => {
    if (tripRefreshInFlight.get(key) === refresh) {
      tripRefreshInFlight.delete(key);
    }
    lease.release();
  });
  tripRefreshInFlight.set(key, refresh);
  return refresh;
}

export function refreshTripsInContext(
  syncContext: ImmutableSyncContext,
): Promise<TripRefreshResult> {
  return coalescedTripRefresh(syncContext);
}

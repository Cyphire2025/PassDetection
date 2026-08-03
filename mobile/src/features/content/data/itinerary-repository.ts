import { apiRequest, ApiError } from '@/core/api/client';
import { principalAccountNamespace } from '@/core/auth/types';
import { useSessionStore } from '@/core/auth/session-store';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';
import {
  assertSyncContextActive,
  type ImmutableSyncContext,
} from '@/core/sync/sync-context';

import { ItinerarySchema, type Itinerary } from '../api/content-contracts';

function namespace(syncContext?: ImmutableSyncContext): string {
  if (syncContext) {
    assertSyncContextActive(syncContext);
    return syncContext.namespace;
  }
  const principal = useSessionStore.getState().session?.principal;
  if (!principal) throw new Error('Authentication is required.');
  return principalAccountNamespace(principal);
}
async function saveItinerary(
  itinerary: Itinerary,
  syncContext?: ImmutableSyncContext,
): Promise<void> {
  const account = namespace(syncContext);
  const database = await openAccountDatabase(account);
  if (syncContext) assertSyncContextActive(syncContext);
  await withAccountTransaction(database, async (transaction) => {
    if (syncContext) assertSyncContextActive(syncContext);
    await transaction.runAsync(
      'DELETE FROM itinerary_days WHERE account_namespace = ? AND trip_id = ?',
      account,
      itinerary.trip_id,
    );
    for (const day of itinerary.days) {
      if (syncContext) assertSyncContextActive(syncContext);
      await transaction.runAsync(
        `INSERT INTO itinerary_days
          (id, account_namespace, trip_id, version, day_number, calendar_date, title, sort_order)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
        day.id,
        account,
        itinerary.trip_id,
        itinerary.version,
        day.day_number,
        day.date,
        day.title,
        day.sort_order,
      );
      for (const item of day.items) {
        if (syncContext) assertSyncContextActive(syncContext);
        await transaction.runAsync(
          `INSERT INTO itinerary_items
            (id, account_namespace, trip_id, day_id, version, title, description, starts_at, ends_at,
             location_name, latitude, longitude, sort_order)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
          item.id,
          account,
          itinerary.trip_id,
          day.id,
          itinerary.version,
          item.title,
          item.description,
          item.starts_at,
          item.ends_at,
          item.location_name,
          item.latitude,
          item.longitude,
          item.sort_order,
        );
      }
    }
  });
}

async function clearItinerary(
  tripId: string,
  syncContext?: ImmutableSyncContext,
): Promise<void> {
  const account = namespace(syncContext);
  const database = await openAccountDatabase(account);
  if (syncContext) assertSyncContextActive(syncContext);
  await withAccountTransaction(database, async (transaction) => {
    if (syncContext) assertSyncContextActive(syncContext);
    await transaction.runAsync(
      'DELETE FROM itinerary_items WHERE account_namespace = ? AND trip_id = ?',
      account,
      tripId,
    );
    await transaction.runAsync(
      'DELETE FROM itinerary_days WHERE account_namespace = ? AND trip_id = ?',
      account,
      tripId,
    );
  });
}

export async function loadLocalItinerary(
  tripId: string,
  syncContext?: ImmutableSyncContext,
): Promise<Itinerary | null> {
  const account = namespace(syncContext);
  const database = await openAccountDatabase(account);
  if (syncContext) assertSyncContextActive(syncContext);
  const days = await database.getAllAsync<{
    id: string;
    version: number;
    day_number: number;
    calendar_date: string | null;
    title: string | null;
    sort_order: number;
  }>(
    `SELECT id, version, day_number, calendar_date, title, sort_order
       FROM itinerary_days
      WHERE account_namespace = ? AND trip_id = ?
      ORDER BY sort_order, day_number`,
    account,
    tripId,
  );
  if (syncContext) assertSyncContextActive(syncContext);
  if (days.length === 0) return null;
  const items = await database.getAllAsync<{
    id: string;
    day_id: string;
    title: string;
    description: string | null;
    starts_at: string | null;
    ends_at: string | null;
    location_name: string | null;
    latitude: number | null;
    longitude: number | null;
    sort_order: number;
  }>(
    `SELECT id, day_id, title, description, starts_at, ends_at, location_name, latitude, longitude, sort_order
       FROM itinerary_items
      WHERE account_namespace = ? AND trip_id = ?
      ORDER BY sort_order`,
    account,
    tripId,
  );
  if (syncContext) assertSyncContextActive(syncContext);
  const version = days[0]?.version ?? 0;
  return {
    trip_id: tripId,
    version,
    title: 'Trip itinerary',
    published_at: new Date(0).toISOString(),
    days: days.map((day) => ({
      id: day.id,
      day_number: day.day_number,
      date: day.calendar_date,
      title: day.title,
      sort_order: day.sort_order,
      items: items
        .filter((item) => item.day_id === day.id)
        .map((item) => ({
          id: item.id,
          title: item.title,
          description: item.description,
          starts_at: item.starts_at,
          ends_at: item.ends_at,
          location_name: item.location_name,
          latitude: item.latitude,
          longitude: item.longitude,
          sort_order: item.sort_order,
        })),
    })),
  };
}

export async function refreshItinerary(
  tripId: string,
  syncContext?: ImmutableSyncContext,
): Promise<{ itinerary: Itinerary | null; offline: boolean }> {
  try {
    if (syncContext) assertSyncContextActive(syncContext);
    const itinerary = await apiRequest(`/mobile/trips/${tripId}/itinerary`, {
      schema: ItinerarySchema,
      ...(syncContext ? { signal: syncContext.signal } : {}),
    });
    if (syncContext) assertSyncContextActive(syncContext);
    await saveItinerary(itinerary, syncContext);
    return { itinerary, offline: false };
  } catch (networkError) {
    if (syncContext) assertSyncContextActive(syncContext);
    if (networkError instanceof ApiError && networkError.status === 404) {
      // A 404 is authoritative publication state, not an offline/network failure.
      // Keeping the prior rows would make an unpublished itinerary visible forever.
      await clearItinerary(tripId, syncContext);
      return { itinerary: null, offline: false };
    }
    const itinerary = await loadLocalItinerary(tripId, syncContext);
    if (itinerary) return { itinerary, offline: true };
    throw networkError;
  }
}

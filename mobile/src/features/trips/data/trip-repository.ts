import { TripListSchema } from '@/core/api/contracts';
import { apiRequest } from '@/core/api/client';
import { accountNamespace } from '@/core/auth/types';
import { useSessionStore } from '@/core/auth/session-store';
import { openAccountDatabase } from '@/core/storage/database';
import { deleteTripVault } from '@/core/storage/vault';
import type { z } from 'zod';

import type { Trip } from '../model/trip';
import { collectCursorPages } from './pagination';

const TRIP_PAGE_SIZE = 100;
const MAX_TRIP_PAGES = 20;
function activeNamespace(): string {
  const principal = useSessionStore.getState().session?.principal;
  if (!principal) throw new Error('Authentication is required.');
  return accountNamespace({ agencyId: principal.agencyId, principalId: principal.id });
}

export async function localTrips(): Promise<Trip[]> {
  const namespace = activeNamespace();
  const database = await openAccountDatabase(namespace);
  const rows = await database.getAllAsync<{
    id: string;
    name: string;
    destination: string | null;
    travel_date: string | null;
    return_date: string | null;
    role: Trip['role'];
    access_generation: number;
    access_expires_at: string | null;
    itinerary_version: number;
    common_document_version: number;
    announcement_version: number;
    updated_at: string;
  }>(
    `SELECT id, name, destination, travel_date, return_date, role, access_generation, access_expires_at,
            itinerary_version, common_document_version, announcement_version, updated_at
       FROM trips
      WHERE account_namespace = ?
      ORDER BY COALESCE(travel_date, '9999-12-31'), name
      LIMIT 2000`,
    namespace,
  );
  return rows.map((row) => ({
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

async function storeTrips(trips: Trip[]): Promise<void> {
  const namespace = activeNamespace();
  const principal = useSessionStore.getState().session?.principal;
  if (!principal) throw new Error('Authentication is required.');
  const database = await openAccountDatabase(namespace);
  const existingIds = await database.getAllAsync<{ id: string }>(
    'SELECT id FROM trips WHERE account_namespace = ?',
    namespace,
  );
  const incoming = new Set(trips.map((trip) => trip.id));
  const removedIds = existingIds.filter((existing) => !incoming.has(existing.id)).map((existing) => existing.id);
  for (const existing of existingIds) {
    if (!incoming.has(existing.id)) await deleteTripVault(namespace, existing.id);
  }
  await database.withTransactionAsync(async () => {
    for (const removedId of removedIds) {
      await database.runAsync(
        'DELETE FROM mobile_notifications WHERE account_namespace = ? AND trip_id = ?',
        namespace, removedId,
      );
    }
    for (const trip of trips) {
      await database.runAsync(
        `INSERT INTO trips (
           id, account_namespace, agency_id, role, name, destination, travel_date, return_date,
           access_generation, access_expires_at, itinerary_version, common_document_version, announcement_version, updated_at
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(id) DO UPDATE SET
           account_namespace = excluded.account_namespace,
           agency_id = excluded.agency_id,
           role = excluded.role,
           name = excluded.name,
           destination = excluded.destination,
           travel_date = excluded.travel_date,
           return_date = excluded.return_date,
           access_generation = excluded.access_generation,
           itinerary_version = excluded.itinerary_version,
           common_document_version = excluded.common_document_version,
           announcement_version = excluded.announcement_version,
           updated_at = excluded.updated_at`,
        trip.id,
        namespace,
        principal.agencyId,
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
      );
    }

    const ids = trips.map((trip) => trip.id);
    if (ids.length > 0) {
      const placeholders = ids.map(() => '?').join(',');
      await database.runAsync(
        `DELETE FROM trips WHERE account_namespace = ? AND id NOT IN (${placeholders})`,
        namespace,
        ...ids,
      );
    } else {
      await database.runAsync('DELETE FROM trips WHERE account_namespace = ?', namespace);
    }
  });
}

export async function refreshTrips(): Promise<{ trips: Trip[]; offline: boolean }> {
  try {
    const items: z.infer<typeof TripListSchema>['items'] = await collectCursorPages(async (cursor) => {
      const query = new URLSearchParams({ limit: String(TRIP_PAGE_SIZE) });
      if (cursor) query.set('cursor', cursor);
      return apiRequest(`/mobile/trips?${query.toString()}`, {
        schema: TripListSchema,
      });
    }, MAX_TRIP_PAGES);

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
    await storeTrips(trips);
    return { trips, offline: false };
  } catch (networkError) {
    const trips = await localTrips();
    if (trips.length > 0) return { trips, offline: true };
    throw networkError;
  }
}

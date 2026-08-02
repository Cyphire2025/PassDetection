import { registerAccessDeniedHandler } from '@/core/api/client';
import { accountNamespace } from '@/core/auth/types';
import { useSessionStore } from '@/core/auth/session-store';
import { openAccountDatabase } from '@/core/storage/database';
import { deleteTripVault } from '@/core/storage/vault';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

import { tripIdFromMobilePath } from './sync-policy';

type PurgeListener = (tripId: string) => void;
const purgeListeners = new Set<PurgeListener>();

function namespace(): string {
  const principal = useSessionStore.getState().session?.principal;
  if (!principal) throw new Error('Authentication is required.');
  return accountNamespace({ agencyId: principal.agencyId, principalId: principal.id });
}

export function subscribeTripPurges(listener: PurgeListener): () => void {
  purgeListeners.add(listener);
  return () => purgeListeners.delete(listener);
}

function publishPurge(tripId: string): void {
  if (useSelectedTripStore.getState().tripId === tripId) useSelectedTripStore.getState().clear();
  for (const listener of purgeListeners) listener(tripId);
}

export async function purgeTripCache(tripId: string): Promise<void> {
  const account = namespace();
  await deleteTripVault(account, tripId).catch(() => undefined);
  const database = await openAccountDatabase(account);
  await database.withTransactionAsync(async () => {
    await database.runAsync(
      'DELETE FROM mobile_notifications WHERE account_namespace = ? AND trip_id = ?',
      account, tripId,
    );
    await database.runAsync('DELETE FROM trips WHERE account_namespace = ? AND id = ?', account, tripId);
  });
  publishPurge(tripId);
}

export async function resetTripCache(tripId: string, nextAccessGeneration: number): Promise<void> {
  const account = namespace();
  await deleteTripVault(account, tripId).catch(() => undefined);
  const database = await openAccountDatabase(account);
  await database.withTransactionAsync(async () => {
    for (const table of [
      'itinerary_days',
      'announcements',
      'document_metadata',
      'passenger_profiles',
      'room_assignments',
      'meal_information',
      'qr_metadata',
      'coordinator_passengers',
      'sync_cursors',
      'pending_actions',
      'attendance_scan_receipts',
      'manager_readiness',
      'attendance_summaries',
      'operation_snapshots',
      'mobile_notifications',
    ]) {
      await database.runAsync(
        `DELETE FROM ${table} WHERE account_namespace = ? AND trip_id = ?`,
        account,
        tripId,
      );
    }
    await database.runAsync(
      'UPDATE trips SET access_generation = ?, access_expires_at = NULL, updated_at = ? WHERE account_namespace = ? AND id = ?',
      nextAccessGeneration,
      new Date().toISOString(),
      account,
      tripId,
    );
  });
  publishPurge(tripId);
}

export async function purgeExpiredTripCaches(now = new Date()): Promise<string[]> {
  if (!useSessionStore.getState().session) return [];
  const account = namespace();
  const database = await openAccountDatabase(account);
  const rows = await database.getAllAsync<{ id: string; access_expires_at: string }>(
    `SELECT id, access_expires_at FROM trips
      WHERE account_namespace = ? AND access_expires_at IS NOT NULL`,
    account,
  );
  const expired = rows.filter((row) => {
    const value = Date.parse(row.access_expires_at);
    return !Number.isFinite(value) || value <= now.getTime();
  });
  for (const trip of expired) await purgeTripCache(trip.id);
  return expired.map((trip) => trip.id);
}

export function installAccessDeniedPurge(): () => void {
  return registerAccessDeniedHandler(async (path) => {
    const tripId = tripIdFromMobilePath(path);
    if (tripId && useSessionStore.getState().session) await purgeTripCache(tripId);
  });
}

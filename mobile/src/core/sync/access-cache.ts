import { registerAccessDeniedHandler } from '@/core/api/client';
import { principalAccountNamespace } from '@/core/auth/types';
import { useSessionStore } from '@/core/auth/session-store';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';
import { completeTripVaultPurge, deleteTripVault } from '@/core/storage/vault';
import {
  assertSyncContextActive,
  captureSyncContext,
  type ImmutableSyncContext,
} from '@/core/sync/sync-context';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

import { isAccessLeaseExpired } from './access-expiry-policy';
import { tripIdFromMobilePath } from './sync-policy';

type PurgeListener = (tripId: string) => void;
const purgeListeners = new Set<PurgeListener>();

export type TripPurgeReason =
  | 'access_revoked'
  | 'access_expired'
  | 'server_removed'
  | 'generation_changed'
  | 'authorization_denied';

type TripPurgeTombstone = {
  account_namespace: string;
  trip_id: string;
  purge_epoch: number;
  blocked_access_generation: number | null;
  reason: TripPurgeReason;
};

export type TripPurgeRetrySummary = {
  completedTripIds: string[];
  pendingTripIds: string[];
};

export class TripVaultPurgePendingError extends Error {
  readonly tripId: string;

  constructor(tripId: string, options?: ErrorOptions) {
    super('Sensitive offline files are still pending secure removal.', options);
    this.name = 'TripVaultPurgePendingError';
    this.tripId = tripId;
  }
}

function namespace(syncContext?: ImmutableSyncContext): string {
  if (syncContext) {
    assertSyncContextActive(syncContext);
    return syncContext.namespace;
  }
  const principal = useSessionStore.getState().session?.principal;
  if (!principal) throw new Error('Authentication is required.');
  return principalAccountNamespace(principal);
}

export function subscribeTripPurges(listener: PurgeListener): () => void {
  purgeListeners.add(listener);
  return () => purgeListeners.delete(listener);
}

function publishPurge(tripId: string, clearSelection = true): void {
  if (clearSelection && useSelectedTripStore.getState().tripId === tripId) {
    useSelectedTripStore.getState().clear();
  }
  for (const listener of purgeListeners) listener(tripId);
}

async function stageTripPurge(
  tripId: string,
  reason: TripPurgeReason,
  syncContext?: ImmutableSyncContext,
  blockedAccessGeneration?: number,
  preserveAuthorizedGenerationState = false,
  authorizedAccessExpiresAt?: string | null,
): Promise<TripPurgeTombstone> {
  const account = namespace(syncContext);
  const database = await openAccountDatabase(account);
  if (syncContext) assertSyncContextActive(syncContext);
  const now = new Date().toISOString();
  let tombstone: TripPurgeTombstone | null = null;
  await withAccountTransaction(database, async (transaction) => {
    if (syncContext) assertSyncContextActive(syncContext);
    const trip = await transaction.getFirstAsync<{ access_generation: number }>(
      'SELECT access_generation FROM trips WHERE account_namespace = ? AND id = ?',
      account,
      tripId,
    );
    const effectiveBlockedGeneration = blockedAccessGeneration ?? trip?.access_generation ?? null;
    if (syncContext) assertSyncContextActive(syncContext);
    await transaction.runAsync(
      `INSERT INTO trip_purge_tombstones (
         account_namespace, trip_id, purge_epoch, blocked_access_generation, reason,
         attempt_count, created_at, updated_at, last_attempt_at, last_error_code
       ) VALUES (?, ?, 1, ?, ?, 0, ?, ?, NULL, NULL)
       ON CONFLICT(account_namespace, trip_id) DO UPDATE SET
         purge_epoch = trip_purge_tombstones.purge_epoch + 1,
         blocked_access_generation = excluded.blocked_access_generation,
         reason = excluded.reason,
         attempt_count = 0,
         updated_at = excluded.updated_at,
         last_attempt_at = NULL,
         last_error_code = NULL`,
      account,
      tripId,
      effectiveBlockedGeneration,
      reason,
      now,
      now,
    );
    tombstone = await transaction.getFirstAsync<TripPurgeTombstone>(
      `SELECT account_namespace, trip_id, purge_epoch, blocked_access_generation, reason
         FROM trip_purge_tombstones
        WHERE account_namespace = ? AND trip_id = ?`,
      account,
      tripId,
    );
    if (!tombstone) throw new Error('The secure trip purge could not be registered.');
    if (syncContext) assertSyncContextActive(syncContext);
    await transaction.runAsync(
      'DELETE FROM mobile_notifications WHERE account_namespace = ? AND trip_id = ?',
      account,
      tripId,
    );
    if (syncContext) assertSyncContextActive(syncContext);
    if (preserveAuthorizedGenerationState) {
      // A generation bump can be caused by an unrelated role/settings change.
      // The successfully authorized manifest proves this role still has access,
      // so retain its durable mutation queue for normal server revalidation.
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
        'attendance_scan_receipts',
        'manager_readiness',
        'attendance_summaries',
        'operation_snapshots',
      ]) {
        if (syncContext) assertSyncContextActive(syncContext);
        await transaction.runAsync(
          `DELETE FROM ${table} WHERE account_namespace = ? AND trip_id = ?`,
          account,
          tripId,
        );
      }
      if (syncContext) assertSyncContextActive(syncContext);
      await transaction.runAsync(
        `UPDATE trips SET
           access_generation = ?, access_expires_at = ?,
           itinerary_version = -1, common_document_version = -1,
           personal_document_version = -1, announcement_version = -1,
           readiness_version = -1, roster_version = -1,
           rooming_version = -1, meals_version = -1, qr_version = -1,
           updated_at = ?
         WHERE account_namespace = ? AND id = ?`,
        effectiveBlockedGeneration,
        authorizedAccessExpiresAt ?? null,
        now,
        account,
        tripId,
      );
    } else {
      // True revocation/removal keeps the existing fail-closed policy: deleting
      // the trip cascades its now-unauthorized queued offline mutations.
      await transaction.runAsync(
        'DELETE FROM trips WHERE account_namespace = ? AND id = ?',
        account,
        tripId,
      );
    }
  });
  if (syncContext) assertSyncContextActive(syncContext);
  publishPurge(tripId, !preserveAuthorizedGenerationState);
  if (!tombstone) throw new Error('The secure trip purge could not be registered.');
  return tombstone;
}

async function recordTripPurgeFailure(
  tombstone: TripPurgeTombstone,
  syncContext?: ImmutableSyncContext,
): Promise<void> {
  if (syncContext) assertSyncContextActive(syncContext);
  const database = await openAccountDatabase(tombstone.account_namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  const attemptedAt = new Date().toISOString();
  await withAccountTransaction(database, async (transaction) => {
    if (syncContext) assertSyncContextActive(syncContext);
    await transaction.runAsync(
      `UPDATE trip_purge_tombstones
          SET attempt_count = attempt_count + 1,
              updated_at = ?, last_attempt_at = ?, last_error_code = 'VAULT_DELETE_FAILED'
        WHERE account_namespace = ? AND trip_id = ? AND purge_epoch = ?`,
      attemptedAt,
      attemptedAt,
      tombstone.account_namespace,
      tombstone.trip_id,
      tombstone.purge_epoch,
    );
  });
}

async function retryTripPurge(
  tombstone: TripPurgeTombstone,
  syncContext?: ImmutableSyncContext,
): Promise<void> {
  try {
    if (syncContext) assertSyncContextActive(syncContext);
    await deleteTripVault(tombstone.account_namespace, tombstone.trip_id);
    if (syncContext) assertSyncContextActive(syncContext);
  } catch (error) {
    if (syncContext) assertSyncContextActive(syncContext);
    await recordTripPurgeFailure(tombstone, syncContext).catch(() => undefined);
    throw new TripVaultPurgePendingError(tombstone.trip_id, { cause: error });
  }

  try {
    const database = await openAccountDatabase(tombstone.account_namespace);
    if (syncContext) assertSyncContextActive(syncContext);
    let finalized = false;
    await withAccountTransaction(database, async (transaction) => {
      if (syncContext) assertSyncContextActive(syncContext);
      // Epoch matching prevents an older retry from acknowledging a newer purge.
      const result = await transaction.runAsync(
        `DELETE FROM trip_purge_tombstones
          WHERE account_namespace = ? AND trip_id = ? AND purge_epoch = ?`,
        tombstone.account_namespace,
        tombstone.trip_id,
        tombstone.purge_epoch,
      );
      finalized = result.changes === 1;
    });
    if (finalized) {
      completeTripVaultPurge(tombstone.account_namespace, tombstone.trip_id);
    }
  } catch (error) {
    if (syncContext) assertSyncContextActive(syncContext);
    throw new TripVaultPurgePendingError(tombstone.trip_id, { cause: error });
  }
}

async function pendingTripPurge(
  tripId: string,
  syncContext?: ImmutableSyncContext,
): Promise<TripPurgeTombstone | null> {
  const account = namespace(syncContext);
  const database = await openAccountDatabase(account);
  if (syncContext) assertSyncContextActive(syncContext);
  return database.getFirstAsync<TripPurgeTombstone>(
    `SELECT account_namespace, trip_id, purge_epoch, blocked_access_generation, reason
       FROM trip_purge_tombstones
      WHERE account_namespace = ? AND trip_id = ?`,
    account,
    tripId,
  );
}

export async function ensureTripPurgeCompleted(
  tripId: string,
  syncContext?: ImmutableSyncContext,
): Promise<void> {
  const tombstone = await pendingTripPurge(tripId, syncContext);
  if (tombstone) await retryTripPurge(tombstone, syncContext);
}

export async function retryPendingTripPurges(
  syncContext?: ImmutableSyncContext,
): Promise<TripPurgeRetrySummary> {
  if (!syncContext && !useSessionStore.getState().session) {
    return { completedTripIds: [], pendingTripIds: [] };
  }
  const account = namespace(syncContext);
  const database = await openAccountDatabase(account);
  if (syncContext) assertSyncContextActive(syncContext);
  const tombstones = await database.getAllAsync<TripPurgeTombstone>(
    `SELECT account_namespace, trip_id, purge_epoch, blocked_access_generation, reason
       FROM trip_purge_tombstones
      WHERE account_namespace = ?
      ORDER BY CASE WHEN last_attempt_at IS NULL THEN 0 ELSE 1 END,
               last_attempt_at, created_at
      LIMIT 2000`,
    account,
  );
  const completedTripIds: string[] = [];
  const pendingTripIds: string[] = [];
  for (const tombstone of tombstones) {
    try {
      await retryTripPurge(tombstone, syncContext);
      completedTripIds.push(tombstone.trip_id);
    } catch (error) {
      if (!(error instanceof TripVaultPurgePendingError)) throw error;
      pendingTripIds.push(tombstone.trip_id);
    }
  }
  return { completedTripIds, pendingTripIds };
}

export async function purgeTripCache(
  tripId: string,
  syncContext?: ImmutableSyncContext,
  reason: TripPurgeReason = 'access_revoked',
): Promise<void> {
  const tombstone = await stageTripPurge(tripId, reason, syncContext);
  await retryTripPurge(tombstone, syncContext);
}

export async function resetTripCache(
  tripId: string,
  nextAccessGeneration: number,
  nextAccessExpiresAt: string | null,
  syncContext?: ImmutableSyncContext,
): Promise<void> {
  const tombstone = await stageTripPurge(
    tripId,
    'generation_changed',
    syncContext,
    nextAccessGeneration,
    true,
    nextAccessExpiresAt,
  );
  await retryTripPurge(tombstone, syncContext);
}

export async function purgeExpiredTripCaches(now = new Date()): Promise<string[]> {
  if (!useSessionStore.getState().session) return [];
  const lease = captureSyncContext();
  try {
    const account = namespace(lease.context);
    const database = await openAccountDatabase(account);
    assertSyncContextActive(lease.context);
    const rows = await database.getAllAsync<{
      id: string;
      access_expires_at: string;
      last_server_time: string | null;
    }>(
      `SELECT trip.id, trip.access_expires_at, cursor.last_synced_at AS last_server_time
         FROM trips trip
         LEFT JOIN sync_cursors cursor
           ON cursor.account_namespace = trip.account_namespace AND cursor.trip_id = trip.id
        WHERE trip.account_namespace = ? AND trip.access_expires_at IS NOT NULL`,
      account,
    );
    assertSyncContextActive(lease.context);
    const expired = rows.filter((row) => isAccessLeaseExpired({
      accessExpiresAt: row.access_expires_at,
      lastServerTime: row.last_server_time,
    }, now.getTime()));
    for (const trip of expired) {
      try {
        await purgeTripCache(trip.id, lease.context, 'access_expired');
      } catch (error) {
        if (!(error instanceof TripVaultPurgePendingError)) throw error;
      }
    }
    return expired.map((trip) => trip.id);
  } finally {
    lease.release();
  }
}

export function installAccessDeniedPurge(): () => void {
  return registerAccessDeniedHandler(async (path) => {
    const tripId = tripIdFromMobilePath(path);
    if (tripId && useSessionStore.getState().session) {
      await purgeTripCache(tripId, undefined, 'authorization_denied');
    }
  });
}

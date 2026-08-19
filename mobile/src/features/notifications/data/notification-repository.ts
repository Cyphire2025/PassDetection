import * as Crypto from 'expo-crypto';
import type { SQLiteDatabase } from 'expo-sqlite';

import { ApiError, apiRequest } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';
import {
  sqliteBindBatches,
  sqliteValuesClause,
  stageSqliteReplacementIds,
} from '@/core/storage/sqlite-batching';
import {
  assertSyncContextActive,
  type ImmutableSyncContext,
} from '@/core/sync/sync-context';

import { MobileNotificationPageSchema, MobileNotificationReadSchema, type MobileNotification } from '../api/notification-contracts';

type PendingNotificationRead = {
  idempotency_key: string;
  dedupe_key: string;
  attempt_count: number;
};

const readDrainInFlight = new Map<string, Promise<void>>();
const READ_CLAIM_STALE_MS = 2 * 60_000;

function readRetryDelay(attempt: number): number {
  const capped = Math.min(Math.max(attempt, 1), 8);
  const base = Math.min(5 * 60_000, 1_000 * 2 ** capped);
  return Math.round(base * (0.75 + Math.random() * 0.5));
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

async function saveNotifications(
  items: MobileNotification[],
  replaceTripId: string | null = null,
  syncContext?: ImmutableSyncContext,
): Promise<void> {
  if (replaceTripId && items.some((item) => item.trip_id !== replaceTripId)) {
    throw new Error('The notification response crossed its authorized trip boundary.');
  }
  const account = namespace(syncContext);
  const database = await openAccountDatabase(account);
  if (syncContext) assertSyncContextActive(syncContext);
  await withAccountTransaction(database, (transaction) => replaceNotificationsInTransaction(
    transaction,
    {
      account,
      items,
      replaceTripId,
      updatedAt: new Date().toISOString(),
      ...(syncContext ? {
        assertActive: () => assertSyncContextActive(syncContext),
      } : {}),
    },
  ));
}

export async function replaceNotificationsInTransaction(
  transaction: SQLiteDatabase,
  options: Readonly<{
    account: string;
    items: readonly MobileNotification[];
    replaceTripId: string | null;
    updatedAt: string;
    assertActive?: () => void;
  }>,
): Promise<void> {
  const { account, assertActive, items, replaceTripId, updatedAt } = options;
  if (replaceTripId && items.some((item) => item.trip_id !== replaceTripId)) {
    throw new Error('The notification response crossed its authorized trip boundary.');
  }
  if (replaceTripId) {
    await stageSqliteReplacementIds(
      transaction,
      'mobile_notification_replacement_ids',
      items.map((item) => item.id),
      assertActive,
    );
  }
  for (const batch of sqliteBindBatches(items, 13)) {
    assertActive?.();
    await transaction.runAsync(
      `INSERT INTO mobile_notifications
        (id, account_namespace, trip_id, notification_type, category, priority, title, body,
         deep_link_path, available_at, expires_at, read_at, updated_at)
       VALUES ${sqliteValuesClause(batch.length, 13)}
       ON CONFLICT(id) DO UPDATE SET
         trip_id = excluded.trip_id, notification_type = excluded.notification_type,
         category = excluded.category, priority = excluded.priority, title = excluded.title,
         body = excluded.body, deep_link_path = excluded.deep_link_path,
         available_at = excluded.available_at, expires_at = excluded.expires_at,
         read_at = COALESCE(mobile_notifications.read_at, excluded.read_at),
         updated_at = excluded.updated_at`,
      ...batch.flatMap((item) => [
        item.id,
        account,
        item.trip_id,
        item.notification_type,
        item.category,
        item.priority,
        item.title,
        item.body,
        item.deep_link_path,
        item.available_at,
        item.expires_at,
        item.read_at,
        updatedAt,
      ]),
    );
  }
  assertActive?.();
  if (replaceTripId) {
    await transaction.runAsync(
      `DELETE FROM mobile_notifications
        WHERE account_namespace = ? AND trip_id = ?
          AND NOT EXISTS (
            SELECT 1 FROM mobile_notification_replacement_ids incoming
             WHERE incoming.id = mobile_notifications.id
          )`,
      account,
      replaceTripId,
    );
  }
  assertActive?.();
}

export async function localNotifications(
  tripId: string,
  syncContext?: ImmutableSyncContext,
): Promise<MobileNotification[]> {
  const account = namespace(syncContext);
  const database = await openAccountDatabase(account);
  if (syncContext) assertSyncContextActive(syncContext);
  const rows = await database.getAllAsync<Omit<MobileNotification, 'payload'>>(
    `SELECT id, trip_id, notification_type, category, priority, title, body, deep_link_path,
            available_at, expires_at, read_at
       FROM mobile_notifications
      WHERE account_namespace = ? AND (trip_id = ? OR trip_id IS NULL)
        AND (expires_at IS NULL OR expires_at > ?)
      ORDER BY available_at DESC LIMIT 200`,
    account, tripId, new Date().toISOString(),
  );
  if (syncContext) assertSyncContextActive(syncContext);
  return rows.map((row) => ({ ...row, payload: {} }));
}

export async function loadNotifications(
  tripId: string,
  cursor: string | null = null,
  syncContext?: ImmutableSyncContext,
) {
  const query = new URLSearchParams({ trip_id: tripId, limit: '100' });
  if (cursor) query.set('cursor', cursor);
  try {
    const result = await apiRequest(`/mobile/notifications?${query.toString()}`, {
      schema: MobileNotificationPageSchema,
      ...(syncContext ? { signal: syncContext.signal } : {}),
    });
    if (syncContext) assertSyncContextActive(syncContext);
    // A complete first page is an authoritative snapshot. Replace it so a revoked
    // announcement cannot be resurrected by the offline cache after the server removes it.
    const replaceTripId = cursor === null && result.next_cursor === null ? tripId : null;
    await saveNotifications(result.items, replaceTripId, syncContext);
    return { ...result, offline: false };
  } catch (networkError) {
    if (syncContext) assertSyncContextActive(syncContext);
    if (cursor) throw networkError;
    const items = await localNotifications(tripId, syncContext);
    if (items.length) return { items, next_cursor: null, unread_count: items.filter((item) => !item.read_at).length, offline: true };
    throw networkError;
  }
}

export async function markNotificationRead(
  notificationId: string,
  tripId: string,
  syncContext?: ImmutableSyncContext,
): Promise<void> {
  const account = namespace(syncContext);
  const database = await openAccountDatabase(account);
  if (syncContext) assertSyncContextActive(syncContext);
  const now = new Date().toISOString();
  await withAccountTransaction(database, async (transaction) => {
    if (syncContext) assertSyncContextActive(syncContext);
    await transaction.runAsync(
      `UPDATE mobile_notifications
          SET read_at = COALESCE(read_at, ?), updated_at = ?
        WHERE account_namespace = ? AND id = ? AND (trip_id = ? OR trip_id IS NULL)`,
      now, now, account, notificationId, tripId,
    );
    await transaction.runAsync(
      `INSERT OR IGNORE INTO pending_actions
        (idempotency_key, account_namespace, trip_id, action_type, dedupe_key, payload_json,
         base_version, state, attempt_count, next_attempt_at, last_error_code, created_at, updated_at)
       VALUES (?, ?, ?, 'notification.read', ?, ?, NULL, 'pending', 0, NULL, NULL, ?, ?)`,
      Crypto.randomUUID(), account, tripId, notificationId,
      JSON.stringify({ notification_id: notificationId }), now, now,
    );
    if (syncContext) assertSyncContextActive(syncContext);
  });
  await drainNotificationReads(tripId, syncContext).catch(() => undefined);
}

async function claimNotificationRead(
  database: Awaited<ReturnType<typeof openAccountDatabase>>,
  account: string,
  tripId: string,
): Promise<PendingNotificationRead | null> {
  let claimed: PendingNotificationRead | null = null;
  await withAccountTransaction(database, async (transaction) => {
    const now = new Date().toISOString();
    const row = await transaction.getFirstAsync<PendingNotificationRead>(
      `SELECT idempotency_key, dedupe_key, attempt_count
         FROM pending_actions
        WHERE account_namespace = ? AND trip_id = ? AND action_type = 'notification.read'
          AND state IN ('pending', 'retryable')
          AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
        ORDER BY created_at, idempotency_key LIMIT 1`,
      account,
      tripId,
      now,
    );
    if (!row) return;
    const result = await transaction.runAsync(
      `UPDATE pending_actions
          SET state = 'sending', attempt_count = attempt_count + 1,
              next_attempt_at = NULL, last_error_code = NULL, updated_at = ?
        WHERE account_namespace = ? AND trip_id = ? AND action_type = 'notification.read'
          AND idempotency_key = ? AND state IN ('pending', 'retryable')`,
      now,
      account,
      tripId,
      row.idempotency_key,
    );
    if (result.changes !== 1) {
      throw new Error('The notification read could not be claimed atomically.');
    }
    claimed = row;
  });
  return claimed;
}

async function drainNotificationReadsForAccount(
  account: string,
  tripId: string,
  syncContext?: ImmutableSyncContext,
): Promise<void> {
  const database = await openAccountDatabase(account);
  if (syncContext) assertSyncContextActive(syncContext);
  const recoveredAt = new Date().toISOString();
  const staleBefore = new Date(Date.now() - READ_CLAIM_STALE_MS).toISOString();
  await database.runAsync(
    `UPDATE pending_actions
        SET state = 'retryable', next_attempt_at = NULL,
            last_error_code = 'INTERRUPTED_RETRY', updated_at = ?
      WHERE account_namespace = ? AND trip_id = ? AND action_type = 'notification.read'
        AND state = 'sending' AND updated_at < ?`,
    recoveredAt,
    account,
    tripId,
    staleBefore,
  );

  while (true) {
    if (syncContext) assertSyncContextActive(syncContext);
    const row = await claimNotificationRead(database, account, tripId);
    if (!row) return;
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(row.dedupe_key)) {
      await database.runAsync(
        `UPDATE pending_actions
            SET state = 'rejected', next_attempt_at = NULL,
                last_error_code = 'INVALID_NOTIFICATION_ID', updated_at = ?
          WHERE account_namespace = ? AND idempotency_key = ? AND state = 'sending'`,
        new Date().toISOString(), account, row.idempotency_key,
      );
      continue;
    }
    try {
      const result = await apiRequest(`/mobile/notifications/${row.dedupe_key}/read`, {
        method: 'POST',
        schema: MobileNotificationReadSchema,
        body: {},
        ...(syncContext ? { signal: syncContext.signal } : {}),
      });
      if (syncContext) assertSyncContextActive(syncContext);
      await withAccountTransaction(database, async (transaction) => {
        if (syncContext) assertSyncContextActive(syncContext);
        await transaction.runAsync(
          `UPDATE mobile_notifications
              SET read_at = ?, updated_at = ?
            WHERE account_namespace = ? AND id = ? AND (trip_id = ? OR trip_id IS NULL)`,
          result.read_at, result.read_at, account, result.id, tripId,
        );
        await transaction.runAsync(
          `DELETE FROM pending_actions
            WHERE account_namespace = ? AND idempotency_key = ? AND state = 'sending'`,
          account,
          row.idempotency_key,
        );
        if (syncContext) assertSyncContextActive(syncContext);
      });
    } catch (error) {
      if (syncContext) assertSyncContextActive(syncContext);
      const permanent = error instanceof ApiError
        && error.status >= 400
        && error.status < 500
        && error.status !== 408
        && error.status !== 429;
      const updatedAt = new Date().toISOString();
      await database.runAsync(
        `UPDATE pending_actions
            SET state = ?, next_attempt_at = ?, last_error_code = ?, updated_at = ?
          WHERE account_namespace = ? AND idempotency_key = ? AND state = 'sending'`,
        permanent ? 'rejected' : 'retryable',
        permanent
          ? null
          : new Date(Date.now() + readRetryDelay(row.attempt_count + 1)).toISOString(),
        error instanceof ApiError ? error.code : 'READ_SYNC_FAILED',
        updatedAt,
        account,
        row.idempotency_key,
      );
      if (!permanent) return;
    }
  }
}

export function drainNotificationReads(
  tripId: string,
  syncContext?: ImmutableSyncContext,
): Promise<void> {
  const account = namespace(syncContext);
  const key = `${account}:${syncContext?.sessionId ?? 'active'}:${tripId}`;
  const active = readDrainInFlight.get(key);
  if (active) return active;
  const request = drainNotificationReadsForAccount(account, tripId, syncContext).finally(() => {
    if (readDrainInFlight.get(key) === request) readDrainInFlight.delete(key);
  });
  readDrainInFlight.set(key, request);
  return request;
}

import * as Crypto from 'expo-crypto';

import { apiRequest } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import { accountNamespace } from '@/core/auth/types';
import { openAccountDatabase } from '@/core/storage/database';

import { MobileNotificationPageSchema, MobileNotificationReadSchema, type MobileNotification } from '../api/notification-contracts';

function namespace(): string {
  const principal = useSessionStore.getState().session?.principal;
  if (!principal) throw new Error('Authentication is required.');
  return accountNamespace({ agencyId: principal.agencyId, principalId: principal.id });
}

async function saveNotifications(items: MobileNotification[]): Promise<void> {
  const account = namespace();
  const database = await openAccountDatabase(account);
  await database.withTransactionAsync(async () => {
    for (const item of items) {
      await database.runAsync(
        `INSERT INTO mobile_notifications
          (id, account_namespace, trip_id, notification_type, category, priority, title, body,
           deep_link_path, available_at, expires_at, read_at, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(id) DO UPDATE SET
           trip_id = excluded.trip_id, notification_type = excluded.notification_type,
           category = excluded.category, priority = excluded.priority, title = excluded.title,
           body = excluded.body, deep_link_path = excluded.deep_link_path,
           available_at = excluded.available_at, expires_at = excluded.expires_at,
           read_at = COALESCE(mobile_notifications.read_at, excluded.read_at),
           updated_at = excluded.updated_at`,
        item.id, account, item.trip_id, item.notification_type, item.category, item.priority,
        item.title, item.body, item.deep_link_path, item.available_at, item.expires_at,
        item.read_at, new Date().toISOString(),
      );
    }
  });
}

export async function localNotifications(tripId: string): Promise<MobileNotification[]> {
  const account = namespace();
  const database = await openAccountDatabase(account);
  const rows = await database.getAllAsync<Omit<MobileNotification, 'payload'>>(
    `SELECT id, trip_id, notification_type, category, priority, title, body, deep_link_path,
            available_at, expires_at, read_at
       FROM mobile_notifications
      WHERE account_namespace = ? AND (trip_id = ? OR trip_id IS NULL)
        AND (expires_at IS NULL OR expires_at > ?)
      ORDER BY available_at DESC LIMIT 200`,
    account, tripId, new Date().toISOString(),
  );
  return rows.map((row) => ({ ...row, payload: {} }));
}

export async function loadNotifications(tripId: string, cursor: string | null = null) {
  const query = new URLSearchParams({ trip_id: tripId, limit: '100' });
  if (cursor) query.set('cursor', cursor);
  try {
    const result = await apiRequest(`/mobile/notifications?${query.toString()}`, { schema: MobileNotificationPageSchema });
    await saveNotifications(result.items);
    return { ...result, offline: false };
  } catch (networkError) {
    if (cursor) throw networkError;
    const items = await localNotifications(tripId);
    if (items.length) return { items, next_cursor: null, unread_count: items.filter((item) => !item.read_at).length, offline: true };
    throw networkError;
  }
}

export async function markNotificationRead(notificationId: string, tripId: string): Promise<void> {
  const account = namespace();
  const database = await openAccountDatabase(account);
  const now = new Date().toISOString();
  await database.withTransactionAsync(async () => {
    await database.runAsync(
      'UPDATE mobile_notifications SET read_at = COALESCE(read_at, ?), updated_at = ? WHERE account_namespace = ? AND id = ?',
      now, now, account, notificationId,
    );
    await database.runAsync(
      `INSERT OR IGNORE INTO pending_actions
        (idempotency_key, account_namespace, trip_id, action_type, dedupe_key, payload_json,
         base_version, state, attempt_count, next_attempt_at, last_error_code, created_at, updated_at)
       VALUES (?, ?, ?, 'notification.read', ?, ?, NULL, 'pending', 0, NULL, NULL, ?, ?)`,
      Crypto.randomUUID(), account, tripId, notificationId,
      JSON.stringify({ notification_id: notificationId }), now, now,
    );
  });
  await drainNotificationReads(tripId).catch(() => undefined);
}

export async function drainNotificationReads(tripId: string): Promise<void> {
  const account = namespace();
  const database = await openAccountDatabase(account);
  while (true) {
    const row = await database.getFirstAsync<{ idempotency_key: string; dedupe_key: string }>(
      `SELECT idempotency_key, dedupe_key FROM pending_actions
        WHERE account_namespace = ? AND trip_id = ? AND action_type = 'notification.read'
          AND state IN ('pending', 'retryable') ORDER BY created_at LIMIT 1`,
      account, tripId,
    );
    if (!row) return;
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(row.dedupe_key)) {
      await database.runAsync(
        `UPDATE pending_actions SET state = 'rejected', last_error_code = 'INVALID_NOTIFICATION_ID', updated_at = ?
          WHERE account_namespace = ? AND idempotency_key = ?`,
        new Date().toISOString(), account, row.idempotency_key,
      );
      continue;
    }
    try {
      const result = await apiRequest(`/mobile/notifications/${row.dedupe_key}/read`, {
        method: 'POST', schema: MobileNotificationReadSchema, body: {},
      });
      await database.withTransactionAsync(async () => {
        await database.runAsync(
          'UPDATE mobile_notifications SET read_at = ?, updated_at = ? WHERE account_namespace = ? AND id = ?',
          result.read_at, result.read_at, account, result.id,
        );
        await database.runAsync('DELETE FROM pending_actions WHERE account_namespace = ? AND idempotency_key = ?', account, row.idempotency_key);
      });
    } catch {
      await database.runAsync(
        `UPDATE pending_actions SET state = 'retryable', attempt_count = attempt_count + 1,
          next_attempt_at = ?, last_error_code = 'READ_SYNC_FAILED', updated_at = ?
          WHERE account_namespace = ? AND idempotency_key = ?`,
        new Date(Date.now() + 30_000).toISOString(), new Date().toISOString(), account, row.idempotency_key,
      );
      return;
    }
  }
}

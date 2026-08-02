import { apiRequest } from '@/core/api/client';
import { accountNamespace } from '@/core/auth/types';
import { useSessionStore } from '@/core/auth/session-store';
import { openAccountDatabase } from '@/core/storage/database';

import {
  AttendanceSummarySchema,
  CoordinatorPassengerSchema,
  CoordinatorRosterSchema,
} from '../api/coordinator-contracts';
import { collectAndReplaceRoster } from './full-roster-sync';

function namespace(): string {
  const principal = useSessionStore.getState().session?.principal;
  if (!principal || principal.principalType !== 'coordinator') throw new Error('Coordinator authentication is required.');
  return accountNamespace({ agencyId: principal.agencyId, principalId: principal.id });
}

async function saveRoster(tripId: string, items: Awaited<ReturnType<typeof remoteRoster>>['items']) {
  const account = namespace();
  const database = await openAccountDatabase(account);
  const updatedAt = new Date().toISOString();
  await database.withTransactionAsync(async () => {
    for (const item of items) {
      await database.runAsync(
        `INSERT INTO coordinator_passengers
          (id, account_namespace, trip_id, display_name, employee_code, attendance_status,
           room_number, meal_preference, has_alert, roster_version, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
         ON CONFLICT(account_namespace, trip_id, id) DO UPDATE SET
           display_name = excluded.display_name,
           employee_code = excluded.employee_code,
           attendance_status = excluded.attendance_status,
           room_number = excluded.room_number,
           meal_preference = excluded.meal_preference,
           has_alert = excluded.has_alert,
           roster_version = 0,
           updated_at = excluded.updated_at`,
        item.id,
        account,
        tripId,
        item.display_name,
        item.employee_code,
        item.attendance_status,
        item.room_number,
        item.meal_preference,
        item.has_alert ? 1 : 0,
        updatedAt,
      );
    }
  });
}

export type CoordinatorPassengerChange = {
  passengerId: string;
  operation: 'upsert' | 'delete';
};

export async function applyCoordinatorPassengerChanges(
  tripId: string,
  changes: CoordinatorPassengerChange[],
): Promise<void> {
  const account = namespace();
  const database = await openAccountDatabase(account);
  const latest = new Map(changes.map((change) => [change.passengerId, change]));
  const bounded = [...latest.values()];
  for (let offset = 0; offset < bounded.length; offset += 6) {
    await Promise.all(
      bounded.slice(offset, offset + 6).map(async (change) => {
        if (change.operation === 'delete') {
          await database.runAsync(
            `DELETE FROM coordinator_passengers
              WHERE account_namespace = ? AND trip_id = ? AND id = ?`,
            account,
            tripId,
            change.passengerId,
          );
          return;
        }
        const passenger = await apiRequest(
          `/mobile/coordinator/groups/${tripId}/passengers/${change.passengerId}`,
          { schema: CoordinatorPassengerSchema },
        );
        if (passenger.id !== change.passengerId) {
          throw new Error('Coordinator passenger synchronization was out of scope.');
        }
        await saveRoster(tripId, [passenger]);
      }),
    );
  }
}

async function replaceRoster(tripId: string, items: Awaited<ReturnType<typeof remoteRoster>>['items']) {
  const account = namespace();
  const database = await openAccountDatabase(account);
  const updatedAt = new Date().toISOString();
  await database.withTransactionAsync(async () => {
    for (const item of items) {
      await database.runAsync(
        `INSERT INTO coordinator_passengers
          (id, account_namespace, trip_id, display_name, employee_code, attendance_status,
           room_number, meal_preference, has_alert, roster_version, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
         ON CONFLICT(account_namespace, trip_id, id) DO UPDATE SET
           display_name = excluded.display_name, employee_code = excluded.employee_code,
           attendance_status = excluded.attendance_status, room_number = excluded.room_number,
           meal_preference = excluded.meal_preference, has_alert = excluded.has_alert,
           roster_version = 0, updated_at = excluded.updated_at`,
        item.id, account, tripId, item.display_name, item.employee_code, item.attendance_status,
        item.room_number, item.meal_preference, item.has_alert ? 1 : 0, updatedAt,
      );
    }
    await database.runAsync(
      `DELETE FROM coordinator_passengers
        WHERE account_namespace = ? AND trip_id = ? AND roster_version = -1`,
      account, tripId,
    );
  });
}

async function localRoster(tripId: string, search: string, cursor: string | null = null) {
  const account = namespace();
  const database = await openAccountDatabase(account);
  if (cursor && !/^local:\d{1,7}$/.test(cursor)) throw new Error('The online roster page is not available offline.');
  const offset = cursor ? Number(cursor.slice('local:'.length)) : 0;
  const pageSize = 100;
  const pattern = `%${search.trim().replaceAll('%', '\\%').replaceAll('_', '\\_')}%`;
  const count = await database.getFirstAsync<{ count: number }>(
    `SELECT COUNT(*) AS count FROM coordinator_passengers
      WHERE account_namespace = ? AND trip_id = ?
        AND (? = '' OR display_name LIKE ? ESCAPE '\\' OR employee_code LIKE ? ESCAPE '\\')`,
    account, tripId, search.trim(), pattern, pattern,
  );
  const items = await database.getAllAsync<{
    id: string;
    display_name: string;
    employee_code: string | null;
    attendance_status: 'not_marked' | 'present' | 'missing' | 'excused';
    room_number: string | null;
    meal_preference: string | null;
    has_alert: number;
  }>(
    `SELECT id, display_name, employee_code, attendance_status, room_number, meal_preference, has_alert
       FROM coordinator_passengers
      WHERE account_namespace = ? AND trip_id = ?
        AND (? = '' OR display_name LIKE ? ESCAPE '\\' OR employee_code LIKE ? ESCAPE '\\')
      ORDER BY display_name
      LIMIT ? OFFSET ?`,
    account,
    tripId,
    search.trim(),
    pattern,
    pattern,
    pageSize,
    offset,
  );
  const total = count?.count ?? 0;
  return {
    items: items.map((item) => ({ ...item, has_alert: Boolean(item.has_alert) })),
    next_cursor: offset + items.length < total ? `local:${offset + items.length}` : null,
    total,
    offline: true,
  };
}

function remoteRoster(tripId: string, search = '', cursor: string | null = null) {
  const query = new URLSearchParams({ limit: '100' });
  if (search.trim()) query.set('search', search.trim());
  if (cursor) query.set('cursor', cursor);
  return apiRequest(`/mobile/coordinator/groups/${tripId}/passengers?${query.toString()}`, {
    schema: CoordinatorRosterSchema,
  });
}

export async function loadRoster(tripId: string, search = '', cursor: string | null = null) {
  try {
    const result = await remoteRoster(tripId, search, cursor);
    await saveRoster(tripId, result.items);
    return { ...result, offline: false };
  } catch (networkError) {
    const local = await localRoster(tripId, search, cursor);
    if (local.items.length) return local;
    throw networkError;
  }
}

export async function syncFullRoster(tripId: string) {
  let total = 0;
  const items = await collectAndReplaceRoster(
    async (cursor) => {
      const page = await remoteRoster(tripId, '', cursor);
      total = page.total;
      return page;
    },
    (complete) => replaceRoster(tripId, complete),
    25,
  );
  return { items, next_cursor: null, total, offline: false };
}

export function loadAttendanceSummary(tripId: string) {
  return refreshAttendanceSummary(tripId);
}

async function localAttendanceSummary(tripId: string) {
  const account = namespace();
  const database = await openAccountDatabase(account);
  const row = await database.getFirstAsync<{
    total: number;
    present: number;
    missing: number;
    excused: number;
    not_marked: number;
    version: number;
    updated_at: string;
  }>(
    `SELECT total, present, missing, excused, not_marked, version, updated_at
       FROM attendance_summaries
      WHERE account_namespace = ? AND trip_id = ?`,
    account,
    tripId,
  );
  return row ? { trip_id: tripId, ...row } : null;
}

async function refreshAttendanceSummary(tripId: string) {
  try {
    const summary = await apiRequest(`/mobile/coordinator/groups/${tripId}/attendance/summary`, {
      schema: AttendanceSummarySchema,
    });
    const account = namespace();
    const database = await openAccountDatabase(account);
    await database.runAsync(
      `INSERT INTO attendance_summaries
        (account_namespace, trip_id, total, present, missing, excused, not_marked, version, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(account_namespace, trip_id) DO UPDATE SET
         total = excluded.total,
         present = excluded.present,
         missing = excluded.missing,
         excused = excluded.excused,
         not_marked = excluded.not_marked,
         version = excluded.version,
         updated_at = excluded.updated_at`,
      account,
      tripId,
      summary.total,
      summary.present,
      summary.missing,
      summary.excused,
      summary.not_marked,
      summary.version,
      summary.updated_at,
    );
    return { summary, offline: false };
  } catch (networkError) {
    const summary = await localAttendanceSummary(tripId);
    if (summary) return { summary, offline: true };
    throw networkError;
  }
}

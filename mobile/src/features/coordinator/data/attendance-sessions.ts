import * as Crypto from 'expo-crypto';
import type { SQLiteDatabase } from 'expo-sqlite';
import { z } from 'zod';

import { apiRequest } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';
import { isDemoMode } from '@/core/demo/demo-mode';
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
import { collectCursorItems } from '@/features/content/data/cursor-pagination';

import {
  AttendanceSessionDetailSchema,
  AttendanceSessionPageSchema,
  AttendanceRosterPageSchema,
  AttendanceSessionSchema,
  type AttendanceRosterPassenger,
  type AttendanceSession,
  type MissingPassenger,
} from '../api/coordinator-contracts';
import {
  MOBILE_ATTENDANCE_ROSTER_CAPACITY,
  MOBILE_ATTENDANCE_SESSION_CAPACITY,
} from './attendance-capacity';

const CreateSessionSchema = z.object({ name: z.string().trim().min(2).max(160) }).strict();

function namespace(syncContext?: ImmutableSyncContext): string {
  if (syncContext) {
    assertSyncContextActive(syncContext);
    if (syncContext.role !== 'coordinator') {
      throw new Error('Coordinator authentication is required.');
    }
    return syncContext.namespace;
  }
  const principal = useSessionStore.getState().session?.principal;
  if (!principal || principal.principalType !== 'coordinator') {
    throw new Error('Coordinator authentication is required.');
  }
  return principalAccountNamespace(principal);
}

async function upsertSession(
  tripId: string,
  session: AttendanceSession,
  transaction?: SQLiteDatabase,
  syncContext?: ImmutableSyncContext,
): Promise<void> {
  const account = namespace(syncContext);
  const database = transaction ?? await openAccountDatabase(account);
  if (syncContext) assertSyncContextActive(syncContext);
  await database.runAsync(
    `INSERT INTO attendance_sessions
      (id, account_namespace, trip_id, name, status, scanned_count, assigned_count,
       started_at, completed_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(id) DO UPDATE SET
       name = excluded.name, status = excluded.status, scanned_count = excluded.scanned_count,
       assigned_count = excluded.assigned_count, started_at = excluded.started_at,
       completed_at = excluded.completed_at, updated_at = excluded.updated_at`,
    session.id,
    account,
    tripId,
    session.name,
    session.status,
    session.scanned_count,
    session.assigned_count,
    session.started_at,
    session.completed_at,
    new Date().toISOString(),
  );
  if (syncContext) assertSyncContextActive(syncContext);
}

async function replaceSessions(
  tripId: string,
  sessions: AttendanceSession[],
  syncContext?: ImmutableSyncContext,
): Promise<void> {
  const account = namespace(syncContext);
  const database = await openAccountDatabase(account);
  if (syncContext) assertSyncContextActive(syncContext);
  await withAccountTransaction(database, (transaction) => replaceAttendanceSessionsInTransaction(
    transaction,
    {
      account,
      tripId,
      sessions,
      updatedAt: new Date().toISOString(),
      ...(syncContext ? {
        assertActive: () => assertSyncContextActive(syncContext),
      } : {}),
    },
  ));
}

export async function replaceAttendanceSessionsInTransaction(
  transaction: SQLiteDatabase,
  options: Readonly<{
    account: string;
    tripId: string;
    sessions: readonly AttendanceSession[];
    updatedAt: string;
    assertActive?: () => void;
  }>,
): Promise<void> {
  const { account, assertActive, sessions, tripId, updatedAt } = options;
  await stageSqliteReplacementIds(
    transaction,
    'mobile_attendance_session_replacement_ids',
    sessions.map((session) => session.id),
    assertActive,
  );
  for (const batch of sqliteBindBatches(sessions, 10)) {
    assertActive?.();
    await transaction.runAsync(
      `INSERT INTO attendance_sessions
        (id, account_namespace, trip_id, name, status, scanned_count, assigned_count,
         started_at, completed_at, updated_at)
       VALUES ${sqliteValuesClause(batch.length, 10)}
       ON CONFLICT(id) DO UPDATE SET
         name = excluded.name, status = excluded.status, scanned_count = excluded.scanned_count,
         assigned_count = excluded.assigned_count, started_at = excluded.started_at,
         completed_at = excluded.completed_at, updated_at = excluded.updated_at`,
      ...batch.flatMap((session) => [
        session.id,
        account,
        tripId,
        session.name,
        session.status,
        session.scanned_count,
        session.assigned_count,
        session.started_at,
        session.completed_at,
        updatedAt,
      ]),
    );
  }
  assertActive?.();
  await transaction.runAsync(
    `DELETE FROM attendance_sessions
      WHERE account_namespace = ? AND trip_id = ?
        AND NOT EXISTS (
          SELECT 1 FROM mobile_attendance_session_replacement_ids incoming
           WHERE incoming.id = attendance_sessions.id
        )`,
    account,
    tripId,
  );
  await transaction.runAsync(
    `DELETE FROM attendance_session_selection
      WHERE account_namespace = ? AND trip_id = ?
        AND session_id NOT IN (
          SELECT id FROM attendance_sessions
           WHERE account_namespace = ? AND trip_id = ? AND status IN ('draft', 'active')
        )`,
    account,
    tripId,
    account,
    tripId,
  );
  assertActive?.();
}

async function localSessions(
  tripId: string,
  syncContext?: ImmutableSyncContext,
): Promise<AttendanceSession[]> {
  const account = namespace(syncContext);
  const database = await openAccountDatabase(account);
  if (syncContext) assertSyncContextActive(syncContext);
  const sessions = await database.getAllAsync<AttendanceSession>(
    `SELECT id, name, status, scanned_count, assigned_count, started_at, completed_at
       FROM attendance_sessions
      WHERE account_namespace = ? AND trip_id = ?
      ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END,
               started_at DESC, name`,
    account,
    tripId,
  );
  if (syncContext) assertSyncContextActive(syncContext);
  return sessions;
}

export async function loadCachedAttendanceSessions(
  tripId: string,
  syncContext?: ImmutableSyncContext,
) {
  const items = await localSessions(tripId, syncContext);
  const current = await selectedAttendanceSession(tripId, syncContext);
  return { items, selectedSessionId: current?.id ?? null, offline: true };
}

export async function selectedAttendanceSession(
  tripId: string,
  syncContext?: ImmutableSyncContext,
): Promise<AttendanceSession | null> {
  const account = namespace(syncContext);
  const database = await openAccountDatabase(account);
  if (syncContext) assertSyncContextActive(syncContext);
  const session = await database.getFirstAsync<AttendanceSession>(
    `SELECT s.id, s.name, s.status, s.scanned_count, s.assigned_count, s.started_at, s.completed_at
       FROM attendance_session_selection p
       JOIN attendance_sessions s ON s.id = p.session_id
        AND s.account_namespace = p.account_namespace AND s.trip_id = p.trip_id
      WHERE p.account_namespace = ? AND p.trip_id = ? AND s.status IN ('draft', 'active')`,
    account,
    tripId,
  );
  if (syncContext) assertSyncContextActive(syncContext);
  return session;
}

export async function selectAttendanceSession(tripId: string, sessionId: string): Promise<void> {
  const account = namespace();
  const database = await openAccountDatabase(account);
  const eligible = await database.getFirstAsync<{ id: string }>(
    `SELECT id FROM attendance_sessions
      WHERE account_namespace = ? AND trip_id = ? AND id = ? AND status IN ('draft', 'active')`,
    account,
    tripId,
    sessionId,
  );
  if (!eligible) throw new Error('Only an active attendance activity can receive scans.');
  await database.runAsync(
    `INSERT INTO attendance_session_selection (account_namespace, trip_id, session_id, selected_at)
     VALUES (?, ?, ?, ?)
     ON CONFLICT(account_namespace, trip_id) DO UPDATE SET
       session_id = excluded.session_id, selected_at = excluded.selected_at`,
    account,
    tripId,
    sessionId,
    new Date().toISOString(),
  );
}

export async function refreshAttendanceSessions(
  tripId: string,
  syncContext?: ImmutableSyncContext,
  onPage?: (items: readonly AttendanceSession[]) => void | Promise<void>,
) {
  try {
    const items = await collectCursorItems<AttendanceSession>(
      (cursor) => {
        if (syncContext) assertSyncContextActive(syncContext);
        return apiRequest(
          `/mobile/coordinator/groups/${tripId}/attendance/sessions?limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`,
          {
            schema: AttendanceSessionPageSchema,
            ...(syncContext ? { signal: syncContext.signal } : {}),
          },
        );
      },
      {
        maxItems: MOBILE_ATTENDANCE_SESSION_CAPACITY,
        itemKey: (session) => session.id,
        ...(syncContext ? {
          assertActive: () => assertSyncContextActive(syncContext),
        } : {}),
        ...(onPage ? {
          onPage: (progress) => onPage(progress.items),
        } : {}),
      },
    );
    if (syncContext) assertSyncContextActive(syncContext);
    await replaceSessions(tripId, items, syncContext);
    const current = await selectedAttendanceSession(tripId, syncContext);
    return { items, selectedSessionId: current?.id ?? null, offline: false };
  } catch (networkError) {
    if (syncContext) assertSyncContextActive(syncContext);
    const items = await localSessions(tripId, syncContext);
    if (items.length) {
      const current = await selectedAttendanceSession(tripId, syncContext);
      return { items, selectedSessionId: current?.id ?? null, offline: true };
    }
    throw networkError;
  }
}

export async function createAttendanceSession(tripId: string, name: string): Promise<AttendanceSession> {
  const input = CreateSessionSchema.parse({ name });
  if (isDemoMode()) {
    const account = namespace();
    const database = await openAccountDatabase(account);
    const roster = await database.getFirstAsync<{ count: number }>(
      `SELECT COUNT(*) AS count FROM coordinator_passengers
        WHERE account_namespace = ? AND trip_id = ?`,
      account,
      tripId,
    );
    const session: AttendanceSession = {
      id: Crypto.randomUUID(),
      name: input.name,
      status: 'active',
      scanned_count: 0,
      assigned_count: roster?.count ?? 0,
      started_at: new Date().toISOString(),
      completed_at: null,
    };
    await upsertSession(tripId, session);
    await selectAttendanceSession(tripId, session.id);
    return session;
  }
  const session = await apiRequest(`/mobile/coordinator/groups/${tripId}/attendance/sessions`, {
    method: 'POST',
    body: input,
    schema: AttendanceSessionSchema,
  });
  await upsertSession(tripId, session);
  if (session.status === 'active' || session.status === 'draft') {
    await selectAttendanceSession(tripId, session.id);
  }
  return session;
}

async function saveMissing(
  tripId: string,
  sessionId: string,
  missing: MissingPassenger[],
  syncContext?: ImmutableSyncContext,
): Promise<void> {
  const account = namespace(syncContext);
  const database = await openAccountDatabase(account);
  if (syncContext) assertSyncContextActive(syncContext);
  const now = new Date().toISOString();
  await withAccountTransaction(database, (transaction) => replaceMissingAttendanceInTransaction(
    transaction,
    {
      account,
      tripId,
      sessionId,
      missing,
      updatedAt: now,
      ...(syncContext ? {
        assertActive: () => assertSyncContextActive(syncContext),
      } : {}),
    },
  ));
}

export async function replaceMissingAttendanceInTransaction(
  transaction: SQLiteDatabase,
  options: Readonly<{
    account: string;
    tripId: string;
    sessionId: string;
    missing: readonly MissingPassenger[];
    updatedAt: string;
    assertActive?: () => void;
  }>,
): Promise<void> {
  const { account, assertActive, missing, sessionId, tripId, updatedAt } = options;
  if (new Set(missing.map((passenger) => passenger.id)).size !== missing.length) {
    throw new Error('The missing-attendee replacement repeated a passenger.');
  }
  assertActive?.();
  await transaction.runAsync(
    `DELETE FROM attendance_session_missing
      WHERE account_namespace = ? AND trip_id = ? AND session_id = ?`,
    account,
    tripId,
    sessionId,
  );
  for (const batch of sqliteBindBatches(missing, 6)) {
    assertActive?.();
    await transaction.runAsync(
      `INSERT INTO attendance_session_missing
        (account_namespace, trip_id, session_id, passenger_id, display_name, updated_at)
       VALUES ${sqliteValuesClause(batch.length, 6)}`,
      ...batch.flatMap((passenger) => [
        account,
        tripId,
        sessionId,
        passenger.id,
        passenger.display_name,
        updatedAt,
      ]),
    );
  }
  assertActive?.();
}

async function localMissing(
  tripId: string,
  sessionId: string,
  syncContext?: ImmutableSyncContext,
): Promise<MissingPassenger[]> {
  const account = namespace(syncContext);
  const database = await openAccountDatabase(account);
  if (syncContext) assertSyncContextActive(syncContext);
  const missing = await database.getAllAsync<MissingPassenger>(
    `SELECT passenger_id AS id, display_name FROM attendance_session_missing
      WHERE account_namespace = ? AND trip_id = ? AND session_id = ?
      ORDER BY display_name`,
    account,
    tripId,
    sessionId,
  );
  if (syncContext) assertSyncContextActive(syncContext);
  return missing;
}

export async function loadCachedAttendanceSessionDetail(
  tripId: string,
  sessionId: string,
  syncContext?: ImmutableSyncContext,
) {
  const session = (await localSessions(tripId, syncContext))
    .find((item) => item.id === sessionId) ?? null;
  if (!session) return null;
  return {
    session,
    missing: await localMissing(tripId, sessionId, syncContext),
    offline: true,
  };
}

export async function loadAttendanceSessionDetail(
  tripId: string,
  sessionId: string,
  syncContext?: ImmutableSyncContext,
  onPage?: (progress: Readonly<{
    session: AttendanceSession;
    missing: readonly MissingPassenger[];
  }>) => void | Promise<void>,
) {
  try {
    let resolvedSession: AttendanceSession | null = null;
    const missing = await collectCursorItems<MissingPassenger>(
      async (cursor) => {
        if (syncContext) assertSyncContextActive(syncContext);
        const page = await apiRequest(
          `/mobile/coordinator/groups/${tripId}/attendance/sessions/${sessionId}?limit=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`,
          {
            schema: AttendanceSessionDetailSchema,
            ...(syncContext ? { signal: syncContext.signal } : {}),
          },
        );
        if (syncContext) assertSyncContextActive(syncContext);
        if (page.session.id !== sessionId || (resolvedSession && page.session.id !== resolvedSession.id)) {
          throw new Error('Attendance activity details were out of scope.');
        }
        resolvedSession = page.session;
        return { items: page.missing, next_cursor: page.next_cursor };
      },
      {
        maxItems: MOBILE_ATTENDANCE_ROSTER_CAPACITY,
        itemKey: (passenger) => passenger.id,
        ...(syncContext ? {
          assertActive: () => assertSyncContextActive(syncContext),
        } : {}),
        ...(onPage ? {
          onPage: async (progress) => {
            if (!resolvedSession) throw new Error('Attendance activity details were empty.');
            await onPage({ session: resolvedSession, missing: progress.items });
          },
        } : {}),
      },
    );
    if (!resolvedSession) throw new Error('Attendance activity details were empty.');
    if (syncContext) assertSyncContextActive(syncContext);
    await upsertSession(tripId, resolvedSession, undefined, syncContext);
    await saveMissing(tripId, sessionId, missing, syncContext);
    return { session: resolvedSession, missing, offline: false };
  } catch (networkError) {
    if (syncContext) assertSyncContextActive(syncContext);
    const session = (await localSessions(tripId, syncContext))
      .find((item) => item.id === sessionId) ?? null;
    if (session) {
      return {
        session,
        missing: await localMissing(tripId, sessionId, syncContext),
        offline: true,
      };
    }
    throw networkError;
  }
}

export async function loadCoordinatorAttendanceRoster(
  tripId: string,
  sessionId: string,
  status: 'counted' | 'missing',
  syncContext?: ImmutableSyncContext,
  onPage?: (progress: Readonly<{
    session: AttendanceSession;
    items: readonly AttendanceRosterPassenger[];
  }>) => void | Promise<void>,
): Promise<{ session: AttendanceSession; items: AttendanceRosterPassenger[] }> {
  if (syncContext) assertSyncContextActive(syncContext);
  let resolvedSession: AttendanceSession | null = null;
  const items = await collectCursorItems<AttendanceRosterPassenger>(
    async (cursor) => {
      if (syncContext) assertSyncContextActive(syncContext);
      const page = await apiRequest(
        `/mobile/coordinator/groups/${tripId}/attendance/sessions/${sessionId}/roster?status=${status}&limit=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`,
        {
          schema: AttendanceRosterPageSchema,
          ...(syncContext ? { signal: syncContext.signal } : {}),
        },
      );
      if (syncContext) assertSyncContextActive(syncContext);
      if (page.session.id !== sessionId) {
        throw new Error('Attendance activity details were out of scope.');
      }
      resolvedSession = page.session;
      return { items: page.items, next_cursor: page.next_cursor };
    },
    {
      maxItems: MOBILE_ATTENDANCE_ROSTER_CAPACITY,
      itemKey: (passenger) => passenger.id,
      ...(syncContext ? {
        assertActive: () => assertSyncContextActive(syncContext),
      } : {}),
      ...(onPage ? {
        onPage: async (progress) => {
          if (!resolvedSession) throw new Error('Attendance activity details were empty.');
          await onPage({ session: resolvedSession, items: progress.items });
        },
      } : {}),
    },
  );
  if (syncContext) assertSyncContextActive(syncContext);
  if (!resolvedSession) throw new Error('Attendance activity details were empty.');
  return { session: resolvedSession, items };
}

export async function completeAttendanceSession(tripId: string, sessionId: string): Promise<AttendanceSession> {
  let session: AttendanceSession;
  if (isDemoMode()) {
    const current = (await localSessions(tripId)).find((item) => item.id === sessionId);
    if (!current || current.status !== 'active') {
      throw new Error('Only an active attendance activity can be completed.');
    }
    session = {
      ...current,
      status: 'completed',
      completed_at: new Date().toISOString(),
    };
  } else {
    session = await apiRequest(
      `/mobile/coordinator/groups/${tripId}/attendance/sessions/${sessionId}/complete`,
      { method: 'PUT', body: {}, schema: AttendanceSessionSchema },
    );
  }
  await upsertSession(tripId, session);
  const account = namespace();
  const database = await openAccountDatabase(account);
  await database.runAsync(
    'DELETE FROM attendance_session_selection WHERE account_namespace = ? AND trip_id = ? AND session_id = ?',
    account,
    tripId,
    sessionId,
  );
  return session;
}

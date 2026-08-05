import * as Crypto from 'expo-crypto';
import type { SQLiteDatabase } from 'expo-sqlite';
import { z } from 'zod';

import { apiRequest } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';
import { isDemoMode } from '@/core/demo/demo-mode';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';
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

const CreateSessionSchema = z.object({ name: z.string().trim().min(2).max(160) }).strict();

function namespace(): string {
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
): Promise<void> {
  const account = namespace();
  const database = transaction ?? await openAccountDatabase(account);
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
}

async function replaceSessions(tripId: string, sessions: AttendanceSession[]): Promise<void> {
  const account = namespace();
  const database = await openAccountDatabase(account);
  await withAccountTransaction(database, async (transaction) => {
    const identifiers = sessions.map((session) => session.id);
    for (const session of sessions) await upsertSession(tripId, session, transaction);
    if (identifiers.length) {
      const placeholders = identifiers.map(() => '?').join(',');
      await transaction.runAsync(
        `DELETE FROM attendance_sessions
          WHERE account_namespace = ? AND trip_id = ? AND id NOT IN (${placeholders})`,
        account,
        tripId,
        ...identifiers,
      );
    } else {
      await transaction.runAsync(
        'DELETE FROM attendance_sessions WHERE account_namespace = ? AND trip_id = ?',
        account,
        tripId,
      );
    }
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
  });
}

async function localSessions(tripId: string): Promise<AttendanceSession[]> {
  const account = namespace();
  const database = await openAccountDatabase(account);
  return database.getAllAsync<AttendanceSession>(
    `SELECT id, name, status, scanned_count, assigned_count, started_at, completed_at
       FROM attendance_sessions
      WHERE account_namespace = ? AND trip_id = ?
      ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END,
               started_at DESC, name`,
    account,
    tripId,
  );
}

export async function loadCachedAttendanceSessions(tripId: string) {
  const items = await localSessions(tripId);
  const current = await selectedAttendanceSession(tripId);
  return { items, selectedSessionId: current?.id ?? null, offline: true };
}

export async function selectedAttendanceSession(tripId: string): Promise<AttendanceSession | null> {
  const account = namespace();
  const database = await openAccountDatabase(account);
  return database.getFirstAsync<AttendanceSession>(
    `SELECT s.id, s.name, s.status, s.scanned_count, s.assigned_count, s.started_at, s.completed_at
       FROM attendance_session_selection p
       JOIN attendance_sessions s ON s.id = p.session_id
        AND s.account_namespace = p.account_namespace AND s.trip_id = p.trip_id
      WHERE p.account_namespace = ? AND p.trip_id = ? AND s.status IN ('draft', 'active')`,
    account,
    tripId,
  );
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

export async function refreshAttendanceSessions(tripId: string) {
  try {
    const items = await collectCursorItems(
      (cursor) => apiRequest(
        `/mobile/coordinator/groups/${tripId}/attendance/sessions?limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`,
        { schema: AttendanceSessionPageSchema },
      ),
      { maxPages: 20, maxItems: 2_000 },
    );
    await replaceSessions(tripId, items);
    const current = await selectedAttendanceSession(tripId);
    return { items, selectedSessionId: current?.id ?? null, offline: false };
  } catch (networkError) {
    const items = await localSessions(tripId);
    if (items.length) {
      const current = await selectedAttendanceSession(tripId);
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
): Promise<void> {
  const account = namespace();
  const database = await openAccountDatabase(account);
  const now = new Date().toISOString();
  await withAccountTransaction(database, async (transaction) => {
    await transaction.runAsync(
      `DELETE FROM attendance_session_missing
        WHERE account_namespace = ? AND trip_id = ? AND session_id = ?`,
      account,
      tripId,
      sessionId,
    );
    for (const passenger of missing) {
      await transaction.runAsync(
        `INSERT INTO attendance_session_missing
          (account_namespace, trip_id, session_id, passenger_id, display_name, updated_at)
         VALUES (?, ?, ?, ?, ?, ?)`,
        account,
        tripId,
        sessionId,
        passenger.id,
        passenger.display_name,
        now,
      );
    }
  });
}

async function localMissing(tripId: string, sessionId: string): Promise<MissingPassenger[]> {
  const account = namespace();
  const database = await openAccountDatabase(account);
  return database.getAllAsync<MissingPassenger>(
    `SELECT passenger_id AS id, display_name FROM attendance_session_missing
      WHERE account_namespace = ? AND trip_id = ? AND session_id = ?
      ORDER BY display_name LIMIT 4000`,
    account,
    tripId,
    sessionId,
  );
}

export async function loadCachedAttendanceSessionDetail(tripId: string, sessionId: string) {
  const session = (await localSessions(tripId)).find((item) => item.id === sessionId) ?? null;
  if (!session) return null;
  return { session, missing: await localMissing(tripId, sessionId), offline: true };
}

export async function loadAttendanceSessionDetail(tripId: string, sessionId: string) {
  try {
    let resolvedSession: AttendanceSession | null = null;
    const missing = await collectCursorItems(
      async (cursor) => {
        const page = await apiRequest(
          `/mobile/coordinator/groups/${tripId}/attendance/sessions/${sessionId}?limit=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`,
          { schema: AttendanceSessionDetailSchema },
        );
        if (page.session.id !== sessionId || (resolvedSession && page.session.id !== resolvedSession.id)) {
          throw new Error('Attendance activity details were out of scope.');
        }
        resolvedSession = page.session;
        return { items: page.missing, next_cursor: page.next_cursor };
      },
      { maxPages: 20, maxItems: 4_000 },
    );
    if (!resolvedSession) throw new Error('Attendance activity details were empty.');
    await upsertSession(tripId, resolvedSession);
    await saveMissing(tripId, sessionId, missing);
    return { session: resolvedSession, missing, offline: false };
  } catch (networkError) {
    const session = (await localSessions(tripId)).find((item) => item.id === sessionId) ?? null;
    if (session) return { session, missing: await localMissing(tripId, sessionId), offline: true };
    throw networkError;
  }
}

export async function loadCoordinatorAttendanceRoster(
  tripId: string,
  sessionId: string,
  status: 'counted' | 'missing',
): Promise<{ session: AttendanceSession; items: AttendanceRosterPassenger[] }> {
  let resolvedSession: AttendanceSession | null = null;
  const items = await collectCursorItems(
    async (cursor) => {
      const page = await apiRequest(
        `/mobile/coordinator/groups/${tripId}/attendance/sessions/${sessionId}/roster?status=${status}&limit=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`,
        { schema: AttendanceRosterPageSchema },
      );
      if (page.session.id !== sessionId) {
        throw new Error('Attendance activity details were out of scope.');
      }
      resolvedSession = page.session;
      return { items: page.items, next_cursor: page.next_cursor };
    },
    { maxPages: 20, maxItems: 4_000 },
  );
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

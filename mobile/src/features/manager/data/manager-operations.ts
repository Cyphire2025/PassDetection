import { apiRequest } from '@/core/api/client';
import {
  assertSyncContextActive,
  type ImmutableSyncContext,
} from '@/core/sync/sync-context';
import { collectCursorItems } from '@/features/content/data/cursor-pagination';
import type {
  AttendanceRosterPassenger,
  AttendanceSession,
} from '@/features/coordinator/api/coordinator-contracts';
import {
  MOBILE_ATTENDANCE_ROSTER_CAPACITY,
  MOBILE_ATTENDANCE_SESSION_CAPACITY,
} from '@/features/coordinator/data/attendance-capacity';

import {
  ManagerAttendanceRosterPageSchema,
  ManagerAttendanceSessionPageSchema,
  ManagerPassengerDetailSchema,
  ManagerRosterSchema,
} from '../api/manager-contracts';

export type ManagerDocumentMode = 'all' | 'visa' | 'flight_ticket';
export type AttendanceRosterStatus = 'counted' | 'missing';

export function loadManagerRoster(
  tripId: string,
  search: string,
  cursor: string | null,
  syncContext?: ImmutableSyncContext,
) {
  if (syncContext) assertSyncContextActive(syncContext);
  const query = new URLSearchParams({ limit: '100' });
  if (search.trim()) query.set('search', search.trim());
  if (cursor) query.set('cursor', cursor);
  return apiRequest(`/mobile/manager/groups/${tripId}/passengers?${query.toString()}`, {
    schema: ManagerRosterSchema,
    ...(syncContext ? { signal: syncContext.signal } : {}),
  });
}

export async function loadManagerPassenger(
  tripId: string,
  passengerId: string,
  syncContext?: ImmutableSyncContext,
) {
  if (syncContext) assertSyncContextActive(syncContext);
  const passenger = await apiRequest(
    `/mobile/manager/groups/${tripId}/passengers/${passengerId}`,
    {
      schema: ManagerPassengerDetailSchema,
      ...(syncContext ? { signal: syncContext.signal } : {}),
    },
  );
  if (syncContext) assertSyncContextActive(syncContext);
  return { passenger, offline: false as const };
}

export async function loadManagerAttendanceSessions(
  tripId: string,
  syncContext?: ImmutableSyncContext,
  onPage?: (items: readonly AttendanceSession[]) => void | Promise<void>,
): Promise<{ items: AttendanceSession[] }> {
  if (syncContext) assertSyncContextActive(syncContext);
  const items = await collectCursorItems<AttendanceSession>(
    (cursor) => {
      if (syncContext) assertSyncContextActive(syncContext);
      return apiRequest(
        `/mobile/manager/groups/${tripId}/attendance/sessions?limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`,
        {
          schema: ManagerAttendanceSessionPageSchema,
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
  return { items };
}

export async function loadManagerAttendanceRoster(
  tripId: string,
  sessionId: string,
  status: AttendanceRosterStatus,
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
        `/mobile/manager/groups/${tripId}/attendance/sessions/${sessionId}/roster?status=${status}&limit=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`,
        {
          schema: ManagerAttendanceRosterPageSchema,
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

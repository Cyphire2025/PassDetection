import { apiRequest } from '@/core/api/client';
import { collectCursorItems } from '@/features/content/data/cursor-pagination';
import type {
  AttendanceRosterPassenger,
  AttendanceSession,
} from '@/features/coordinator/api/coordinator-contracts';

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
) {
  const query = new URLSearchParams({ limit: '100' });
  if (search.trim()) query.set('search', search.trim());
  if (cursor) query.set('cursor', cursor);
  return apiRequest(`/mobile/manager/groups/${tripId}/passengers?${query.toString()}`, {
    schema: ManagerRosterSchema,
  });
}

export async function loadManagerPassenger(tripId: string, passengerId: string) {
  const passenger = await apiRequest(
    `/mobile/manager/groups/${tripId}/passengers/${passengerId}`,
    { schema: ManagerPassengerDetailSchema },
  );
  return { passenger, offline: false as const };
}

export async function loadManagerAttendanceSessions(
  tripId: string,
): Promise<{ items: AttendanceSession[] }> {
  const items = await collectCursorItems(
    (cursor) => apiRequest(
      `/mobile/manager/groups/${tripId}/attendance/sessions?limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`,
      { schema: ManagerAttendanceSessionPageSchema },
    ),
    { maxPages: 20, maxItems: 2_000 },
  );
  return { items };
}

export async function loadManagerAttendanceRoster(
  tripId: string,
  sessionId: string,
  status: AttendanceRosterStatus,
): Promise<{ session: AttendanceSession; items: AttendanceRosterPassenger[] }> {
  let resolvedSession: AttendanceSession | null = null;
  const items = await collectCursorItems(
    async (cursor) => {
      const page = await apiRequest(
        `/mobile/manager/groups/${tripId}/attendance/sessions/${sessionId}/roster?status=${status}&limit=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`,
        { schema: ManagerAttendanceRosterPageSchema },
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

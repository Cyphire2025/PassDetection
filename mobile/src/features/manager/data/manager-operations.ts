import { z } from 'zod';

import { apiRequest } from '@/core/api/client';
import {
  assertSyncContextActive,
  type ImmutableSyncContext,
} from '@/core/sync/sync-context';
import { collectCursorItems } from '@/features/content/data/cursor-pagination';
import {
  AttendanceSessionSchema,
  type AttendanceRosterPassenger,
  type AttendanceSession,
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

const ManagerAttendanceSessionCreateSchema = z.object({
  name: z.string().trim().min(2).max(160),
}).strict();

const CloseoutCountSchema = z.number().int().min(0).max(1_000_000);
const AttendanceCloseoutCoordinatorStatusSchema = z.object({
  coordinator_id: z.string().uuid(),
  coordinator_name: z.string().min(1).max(320),
  state: z.enum(['ready', 'missing', 'stale', 'blocked']),
  reported_at: z.string().datetime({ offset: true }).nullable(),
  report_age_seconds: z.number().int().min(0).nullable(),
  pending_count: CloseoutCountSchema,
  sending_count: CloseoutCountSchema,
  retryable_count: CloseoutCountSchema,
  needs_review_count: CloseoutCountSchema,
  unreviewed_rejected_count: CloseoutCountSchema,
  oldest_pending_age_seconds: z.number().int().min(0).nullable(),
}).strict().superRefine((value, context) => {
  const deliveryCount = value.pending_count + value.sending_count + value.retryable_count;
  if ((deliveryCount === 0) !== (value.oldest_pending_age_seconds === null)) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ['oldest_pending_age_seconds'],
      message: 'Oldest pending age did not match the coordinator delivery count.',
    });
  }
  if ((value.reported_at === null) !== (value.report_age_seconds === null)) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ['report_age_seconds'],
      message: 'Report age did not match the coordinator report timestamp.',
    });
  }
});

export const AttendanceCloseoutStatusSchema = z.object({
  ready: z.boolean(),
  checkpoint_ttl_seconds: z.number().int().min(1).max(86_400),
  active_assignment_count: z.number().int().min(0).max(100_000),
  ready_assignment_count: z.number().int().min(0).max(100_000),
  missing_assignment_count: z.number().int().min(0).max(100_000),
  stale_assignment_count: z.number().int().min(0).max(100_000),
  nonzero_assignment_count: z.number().int().min(0).max(100_000),
  blocked_assignment_count: z.number().int().min(0).max(100_000),
  unresolved_count: z.number().int().min(0).max(100_000_000),
  oldest_pending_age_seconds: z.number().int().min(0).nullable(),
  coordinators: z.array(AttendanceCloseoutCoordinatorStatusSchema).max(100_000),
}).strict().superRefine((value, context) => {
  const unresolved = value.coordinators.reduce(
    (sum, coordinator) => sum
      + coordinator.pending_count
      + coordinator.sending_count
      + coordinator.retryable_count
      + coordinator.needs_review_count
      + coordinator.unreviewed_rejected_count,
    0,
  );
  const stateCount = (state: 'ready' | 'missing' | 'stale') => (
    value.coordinators.filter((coordinator) => coordinator.state === state).length
  );
  const aggregateIsConsistent = value.active_assignment_count === value.coordinators.length
    && value.ready_assignment_count === stateCount('ready')
    && value.missing_assignment_count === stateCount('missing')
    && value.stale_assignment_count === stateCount('stale')
    && value.nonzero_assignment_count === value.coordinators.filter((coordinator) => (
      coordinator.pending_count
      + coordinator.sending_count
      + coordinator.retryable_count
      + coordinator.needs_review_count
      + coordinator.unreviewed_rejected_count > 0
    )).length
    && value.blocked_assignment_count
      === value.active_assignment_count - value.ready_assignment_count
    && value.unresolved_count === unresolved
    && value.ready
      === (value.active_assignment_count > 0 && value.blocked_assignment_count === 0);
  if (!aggregateIsConsistent) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: 'Attendance closeout aggregates were inconsistent.',
    });
  }
});

const AttendanceCloseRequestSchema = z.object({
  exception_reason: z.string().trim().min(10).max(500).optional(),
}).strict();

export type AttendanceCloseoutStatus = z.infer<typeof AttendanceCloseoutStatusSchema>;

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

export function completeManagerAttendanceSession(
  tripId: string,
  sessionId: string,
  exceptionReason?: string,
): Promise<AttendanceSession> {
  const normalizedReason = exceptionReason?.trim().replace(/\s+/g, ' ');
  const body = AttendanceCloseRequestSchema.parse({
    ...(normalizedReason ? { exception_reason: normalizedReason } : {}),
  });
  return apiRequest(
    `/mobile/manager/groups/${tripId}/attendance/sessions/${sessionId}/complete`,
    { method: 'PUT', body, schema: AttendanceSessionSchema },
  );
}

export function loadManagerAttendanceCloseoutStatus(
  tripId: string,
  sessionId: string,
): Promise<AttendanceCloseoutStatus> {
  return apiRequest(
    `/mobile/manager/groups/${tripId}/attendance/sessions/${sessionId}/closeout`,
    { schema: AttendanceCloseoutStatusSchema },
  );
}

export function createManagerAttendanceSession(
  tripId: string,
  name: string,
): Promise<AttendanceSession> {
  const body = ManagerAttendanceSessionCreateSchema.parse({ name });
  return apiRequest(
    `/mobile/manager/groups/${tripId}/attendance/sessions`,
    { method: 'POST', body, schema: AttendanceSessionSchema },
  );
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

import { useInfiniteQuery, useQuery } from '@tanstack/react-query';

import { loadAttendanceSummary, loadRoster } from '../data/coordinator-repository';
import { loadAttendanceSessionDetail, refreshAttendanceSessions } from '../data/attendance-sessions';

export function useCoordinatorRoster(tripId: string | null, search: string) {
  return useInfiniteQuery({
    queryKey: ['coordinator-roster', tripId, search.trim()],
    queryFn: ({ pageParam }) => loadRoster(tripId!, search, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    enabled: Boolean(tripId),
  });
}

export function useAttendanceSummary(tripId: string | null) {
  return useQuery({
    queryKey: ['coordinator-attendance-summary', tripId],
    queryFn: () => loadAttendanceSummary(tripId!),
    enabled: Boolean(tripId),
    refetchInterval: 30_000,
  });
}

export function useAttendanceSessions(tripId: string | null) {
  return useQuery({
    queryKey: ['coordinator-attendance-sessions', tripId],
    queryFn: () => refreshAttendanceSessions(tripId!),
    enabled: Boolean(tripId),
  });
}

export function useAttendanceSessionDetail(tripId: string | null, sessionId: string | null) {
  return useQuery({
    queryKey: ['coordinator-attendance-session-detail', tripId, sessionId],
    queryFn: () => loadAttendanceSessionDetail(tripId!, sessionId!),
    enabled: Boolean(tripId && sessionId),
  });
}

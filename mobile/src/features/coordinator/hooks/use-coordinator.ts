import { useInfiniteQuery, useQuery } from '@tanstack/react-query';

import { loadAttendanceSummary, loadCoordinatorPassenger, loadRoster } from '../data/coordinator-repository';
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

export function useCoordinatorPassenger(tripId: string | null, passengerId: string | null) {
  return useQuery({
    queryKey: ['coordinator-passenger', tripId, passengerId],
    queryFn: () => loadCoordinatorPassenger(tripId!, passengerId!),
    enabled: Boolean(tripId && passengerId),
    staleTime: 15_000,
    refetchOnMount: 'always',
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
    staleTime: 5_000,
    refetchOnMount: 'always',
    refetchInterval: (query) => (
      query.state.data?.items.some((session) => session.status === 'active') ? 8_000 : false
    ),
    refetchIntervalInBackground: false,
  });
}

export function useAttendanceSessionDetail(tripId: string | null, sessionId: string | null) {
  return useQuery({
    queryKey: ['coordinator-attendance-session-detail', tripId, sessionId],
    queryFn: () => loadAttendanceSessionDetail(tripId!, sessionId!),
    enabled: Boolean(tripId && sessionId),
  });
}

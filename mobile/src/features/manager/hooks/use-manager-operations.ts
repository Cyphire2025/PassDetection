import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';

import { useSessionStore } from '@/core/auth/session-store';
import { accountNamespace } from '@/core/auth/types';

import {
  loadManagerAttendanceRoster,
  loadManagerAttendanceSessions,
  loadManagerPassenger,
  loadManagerRoster,
  type AttendanceRosterStatus,
} from '../data/manager-operations';

function useManagerAccountKey(): string | null {
  const principal = useSessionStore((state) => state.session?.principal ?? null);
  return principal?.principalType === 'client_manager'
    ? accountNamespace({ agencyId: principal.agencyId, accountId: principal.accountId })
    : null;
}

export function useManagerRoster(tripId: string | null, search: string) {
  const accountKey = useManagerAccountKey();
  const normalizedSearch = search.trim();
  const queryKey = useMemo(
    () => ['manager-roster', accountKey, tripId, normalizedSearch] as const,
    [accountKey, normalizedSearch, tripId],
  );
  return useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam }) => loadManagerRoster(tripId!, normalizedSearch, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    enabled: Boolean(accountKey && tripId),
    staleTime: 15_000,
  });
}

export function useManagerPassenger(tripId: string | null, passengerId: string | null) {
  const accountKey = useManagerAccountKey();
  const queryKey = useMemo(
    () => ['manager-passenger', accountKey, tripId, passengerId] as const,
    [accountKey, passengerId, tripId],
  );
  return useQuery({
    queryKey,
    queryFn: () => loadManagerPassenger(tripId!, passengerId!),
    enabled: Boolean(accountKey && tripId && passengerId),
    staleTime: 15_000,
  });
}

export function useManagerAttendanceSessions(tripId: string | null) {
  const accountKey = useManagerAccountKey();
  const queryKey = useMemo(
    () => ['manager-attendance-sessions', accountKey, tripId] as const,
    [accountKey, tripId],
  );
  return useQuery({
    queryKey,
    queryFn: () => loadManagerAttendanceSessions(tripId!),
    enabled: Boolean(accountKey && tripId),
    staleTime: 5_000,
    refetchInterval: (query) => (
      query.state.data?.items.some((session) => session.status === 'active') ? 8_000 : false
    ),
    refetchIntervalInBackground: false,
  });
}

export function useManagerAttendanceRoster(
  tripId: string | null,
  sessionId: string | null,
  status: AttendanceRosterStatus,
  enabled: boolean,
) {
  const accountKey = useManagerAccountKey();
  const queryKey = useMemo(
    () => ['manager-attendance-roster', accountKey, tripId, sessionId, status] as const,
    [accountKey, sessionId, status, tripId],
  );
  return useQuery({
    queryKey,
    queryFn: () => loadManagerAttendanceRoster(tripId!, sessionId!, status),
    enabled: Boolean(enabled && accountKey && tripId && sessionId),
    staleTime: status === 'counted' ? 5_000 : 2_000,
  });
}

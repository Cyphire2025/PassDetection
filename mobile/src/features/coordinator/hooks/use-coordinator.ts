import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
  type InfiniteData,
} from '@tanstack/react-query';
import { useCallback, useMemo, useRef, useState } from 'react';

import { useSessionStore } from '@/core/auth/session-store';
import { accountNamespace } from '@/core/auth/types';
import { usePersistentQueryHydration } from '@/core/query/use-persistent-query-hydration';
import { useAnnouncements, useCommonDocuments } from '@/features/content/hooks/use-content';
import { useNotifications } from '@/features/notifications/hooks/use-notifications';

import {
  loadCachedCoordinatorPassenger,
  loadCachedRoster,
  loadCoordinatorPassenger,
  loadRoster,
} from '../data/coordinator-repository';
import {
  loadAttendanceSessionDetail,
  loadCachedAttendanceSessionDetail,
  loadCachedAttendanceSessions,
  loadCoordinatorAttendanceRoster,
  refreshAttendanceSessions,
} from '../data/attendance-sessions';

function useCoordinatorAccountKey(): string | null {
  const agencyId = useSessionStore((state) => state.session?.principal.agencyId ?? null);
  const accountId = useSessionStore((state) => state.session?.principal.principalType === 'coordinator'
    ? state.session.principal.accountId
    : null);
  return agencyId && accountId ? accountNamespace({ agencyId, accountId }) : null;
}

export function useCoordinatorRoster(tripId: string | null, search: string) {
  const queryClient = useQueryClient();
  const accountKey = useCoordinatorAccountKey();
  const normalizedSearch = search.trim();
  const refreshLock = useRef(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const queryKey = useMemo(
    () => ['coordinator-roster', accountKey, tripId, normalizedSearch] as const,
    [accountKey, normalizedSearch, tripId],
  );
  const loadCachedRosterQuery = useCallback(async () => {
    const cached = await loadCachedRoster(tripId!, normalizedSearch);
    return {
      pages: [cached],
      pageParams: [null as string | null],
    };
  }, [normalizedSearch, tripId]);
  const cacheHydrated = usePersistentQueryHydration({
    accountKey,
    hydrationKey: tripId ? `coordinator-roster:${tripId}:${normalizedSearch}` : null,
    queryKey,
    load: loadCachedRosterQuery,
  });
  const query = useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam }) => loadRoster(tripId!, search, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    enabled: Boolean(accountKey && tripId && cacheHydrated),
  });
  const refreshFirstPage = useCallback(async () => {
    if (!tripId || refreshLock.current) return;
    refreshLock.current = true;
    setIsRefreshing(true);
    try {
      const fresh = await loadRoster(tripId, normalizedSearch, null);
      queryClient.setQueryData<InfiniteData<typeof fresh, string | null>>(queryKey, {
        pages: [fresh],
        pageParams: [null],
      });
    } catch {
      // Preserve the last account-scoped offline roster when a manual refresh cannot connect.
    } finally {
      refreshLock.current = false;
      setIsRefreshing(false);
    }
  }, [normalizedSearch, queryClient, queryKey, tripId]);
  return { ...query, refreshFirstPage, isRefreshing };
}

export function useCoordinatorPassenger(tripId: string | null, passengerId: string | null) {
  const accountKey = useCoordinatorAccountKey();
  const queryKey = useMemo(
    () => ['coordinator-passenger', accountKey, tripId, passengerId] as const,
    [accountKey, passengerId, tripId],
  );
  const loadCachedPassenger = useCallback(
    async () => {
      const passenger = await loadCachedCoordinatorPassenger(tripId!, passengerId!);
      return passenger ? { passenger, offline: true as const } : null;
    },
    [passengerId, tripId],
  );
  const cacheHydrated = usePersistentQueryHydration({
    accountKey,
    hydrationKey: tripId && passengerId ? `coordinator-passenger:${tripId}:${passengerId}` : null,
    queryKey,
    load: loadCachedPassenger,
  });
  const query = useQuery({
    queryKey,
    queryFn: () => loadCoordinatorPassenger(tripId!, passengerId!),
    enabled: Boolean(accountKey && tripId && passengerId && cacheHydrated),
    staleTime: 15_000,
    refetchOnMount: 'always',
  });
  return query;
}

export function useAttendanceSessions(tripId: string | null) {
  const accountKey = useCoordinatorAccountKey();
  const queryKey = useMemo(
    () => ['coordinator-attendance-sessions', accountKey, tripId] as const,
    [accountKey, tripId],
  );
  const loadCachedSessions = useCallback(
    () => loadCachedAttendanceSessions(tripId!),
    [tripId],
  );
  const cacheHydrated = usePersistentQueryHydration({
    accountKey,
    hydrationKey: tripId ? `coordinator-attendance-sessions:${tripId}` : null,
    queryKey,
    load: loadCachedSessions,
  });
  const query = useQuery({
    queryKey,
    queryFn: () => refreshAttendanceSessions(tripId!),
    enabled: Boolean(accountKey && tripId && cacheHydrated),
    staleTime: 5_000,
    refetchOnMount: 'always',
    refetchInterval: (query) => (
      query.state.data?.items.some((session) => session.status === 'active') ? 8_000 : false
    ),
    refetchIntervalInBackground: false,
  });
  return query;
}

export function useAttendanceSessionDetail(tripId: string | null, sessionId: string | null) {
  const accountKey = useCoordinatorAccountKey();
  const queryKey = useMemo(
    () => ['coordinator-attendance-session-detail', accountKey, tripId, sessionId] as const,
    [accountKey, sessionId, tripId],
  );
  const loadCachedDetail = useCallback(
    () => loadCachedAttendanceSessionDetail(tripId!, sessionId!),
    [sessionId, tripId],
  );
  const cacheHydrated = usePersistentQueryHydration({
    accountKey,
    hydrationKey: tripId && sessionId ? `coordinator-attendance-session-detail:${tripId}:${sessionId}` : null,
    queryKey,
    load: loadCachedDetail,
  });
  const query = useQuery({
    queryKey,
    queryFn: () => loadAttendanceSessionDetail(tripId!, sessionId!),
    enabled: Boolean(accountKey && tripId && sessionId && cacheHydrated),
  });
  return query;
}

export function useCoordinatorAttendanceRoster(
  tripId: string | null,
  sessionId: string | null,
  status: 'counted' | 'missing',
  enabled: boolean,
) {
  const accountKey = useCoordinatorAccountKey();
  const queryKey = useMemo(
    () => ['coordinator-attendance-roster', accountKey, tripId, sessionId, status] as const,
    [accountKey, sessionId, status, tripId],
  );
  return useQuery({
    queryKey,
    queryFn: () => loadCoordinatorAttendanceRoster(tripId!, sessionId!, status),
    enabled: Boolean(enabled && accountKey && tripId && sessionId),
    staleTime: status === 'counted' ? 5_000 : 2_000,
  });
}

export function useCoordinatorCommonDocuments(tripId: string | null) {
  return useCommonDocuments(tripId);
}

export function useCoordinatorAnnouncements(tripId: string | null) {
  return useAnnouncements(tripId);
}

export function useCoordinatorNotifications(tripId: string | null) {
  return useNotifications(tripId);
}

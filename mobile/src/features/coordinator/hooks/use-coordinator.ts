import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
  type InfiniteData,
} from '@tanstack/react-query';
import { useCallback, useMemo, useRef, useState } from 'react';

import { useSessionStore } from '@/core/auth/session-store';
import { accountNamespace } from '@/core/auth/types';
import { withAccountQueryContext } from '@/core/query/account-query-context';
import { activeAttendanceRefreshInterval } from '@/core/query/attendance-refresh-policy';
import { mergeProgressiveItemsById } from '@/core/query/progressive-page';
import { usePersistentQueryHydration } from '@/core/query/use-persistent-query-hydration';
import { useRouteFocus } from '@/core/query/use-route-focus';
import { requestSync } from '@/core/sync/sync-trigger';
import { useAnnouncements, useCommonDocuments } from '@/features/content/hooks/use-content';
import { useNotifications } from '@/features/notifications/hooks/use-notifications';

import {
  loadCachedCoordinatorPassenger,
  loadCachedRoster,
  loadCoordinatorPassenger,
} from '../data/coordinator-repository';
import type { LocalRosterFilter } from '../data/local-roster-search';
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

export function useCoordinatorRoster(
  tripId: string | null,
  search: string,
  filter: LocalRosterFilter = 'all',
) {
  const queryClient = useQueryClient();
  const accountKey = useCoordinatorAccountKey();
  const normalizedSearch = search.trim();
  const refreshLock = useRef(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const queryKey = useMemo(
    () => ['coordinator-roster', accountKey, tripId, normalizedSearch, filter] as const,
    [accountKey, filter, normalizedSearch, tripId],
  );
  const loadCachedRosterQuery = useCallback(async () => {
    const cached = await loadCachedRoster(tripId!, normalizedSearch, null, undefined, filter);
    return {
      pages: [cached],
      pageParams: [null as string | null],
    };
  }, [filter, normalizedSearch, tripId]);
  const cacheHydrated = usePersistentQueryHydration({
    accountKey,
    hydrationKey: tripId
      ? `coordinator-roster:${tripId}:${normalizedSearch}:${filter}`
      : null,
    queryKey,
    load: loadCachedRosterQuery,
  });
  const query = useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam, signal }) => withAccountQueryContext(
      signal,
      (context) => loadCachedRoster(tripId!, normalizedSearch, pageParam, context, filter),
    ),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    enabled: Boolean(accountKey && tripId && cacheHydrated),
  });
  const refreshFirstPage = useCallback(async () => {
    if (!tripId || refreshLock.current) return;
    refreshLock.current = true;
    setIsRefreshing(true);
    try {
      await requestSync({
        scope: 'trip',
        tripId,
        reason: 'manual-coordinator-roster',
      });
      const fresh = await withAccountQueryContext(
        new AbortController().signal,
        (context) => loadCachedRoster(tripId, normalizedSearch, null, context, filter),
      );
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
  }, [filter, normalizedSearch, queryClient, queryKey, tripId]);
  const localRefetch = query.refetch;
  const coordinatedRefetch = useCallback((
    options?: Parameters<typeof localRefetch>[0],
  ) => {
    if (!tripId) return localRefetch(options);
    return requestSync({
      scope: 'trip',
      tripId,
      reason: 'manual-coordinator-roster-query',
    }).then(() => localRefetch(options));
  }, [localRefetch, tripId]);
  return { ...query, refetch: coordinatedRefetch, refreshFirstPage, isRefreshing };
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
    queryFn: ({ signal }) => withAccountQueryContext(
      signal,
      (context) => loadCoordinatorPassenger(tripId!, passengerId!, context),
    ),
    enabled: Boolean(accountKey && tripId && passengerId && cacheHydrated),
    staleTime: 15_000,
    refetchOnMount: 'always',
  });
  return query;
}

export function useAttendanceSessions(tripId: string | null) {
  const queryClient = useQueryClient();
  const accountKey = useCoordinatorAccountKey();
  const routeFocused = useRouteFocus();
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
    queryFn: ({ signal }) => withAccountQueryContext(
      signal,
      (context) => refreshAttendanceSessions(tripId!, context, (items) => {
        queryClient.setQueryData<Awaited<ReturnType<typeof refreshAttendanceSessions>>>(
          queryKey,
          (current) => ({
            items: mergeProgressiveItemsById(items, current?.items),
            selectedSessionId: current?.selectedSessionId ?? null,
            offline: false,
          }),
        );
      }),
    ),
    enabled: Boolean(accountKey && tripId && cacheHydrated),
    staleTime: 5_000,
    refetchOnMount: 'always',
    refetchInterval: (query) => activeAttendanceRefreshInterval({
      hasActiveSession: Boolean(
        query.state.data?.items.some((session) => session.status === 'active'),
      ),
      error: query.state.error,
      routeFocused,
    }),
    refetchIntervalInBackground: false,
  });
  return query;
}

export function useAttendanceSessionDetail(tripId: string | null, sessionId: string | null) {
  const queryClient = useQueryClient();
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
    queryFn: ({ signal }) => withAccountQueryContext(
      signal,
      (context) => loadAttendanceSessionDetail(tripId!, sessionId!, context, (progress) => {
        queryClient.setQueryData<Awaited<ReturnType<typeof loadAttendanceSessionDetail>>>(
          queryKey,
          (current) => ({
            session: progress.session,
            missing: mergeProgressiveItemsById(progress.missing, current?.missing),
            offline: false,
          }),
        );
      }),
    ),
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
  const queryClient = useQueryClient();
  const accountKey = useCoordinatorAccountKey();
  const queryKey = useMemo(
    () => ['coordinator-attendance-roster', accountKey, tripId, sessionId, status] as const,
    [accountKey, sessionId, status, tripId],
  );
  return useQuery({
    queryKey,
    queryFn: ({ signal }) => withAccountQueryContext(
      signal,
      (context) => loadCoordinatorAttendanceRoster(
        tripId!,
        sessionId!,
        status,
        context,
        (progress) => {
          queryClient.setQueryData<Awaited<ReturnType<typeof loadCoordinatorAttendanceRoster>>>(
            queryKey,
            (current) => ({
              session: progress.session,
              items: mergeProgressiveItemsById(progress.items, current?.items),
            }),
          );
        },
      ),
    ),
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

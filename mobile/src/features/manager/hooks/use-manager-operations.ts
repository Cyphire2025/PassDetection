import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo } from 'react';

import { useSessionStore } from '@/core/auth/session-store';
import { accountNamespace } from '@/core/auth/types';
import { withAccountQueryContext } from '@/core/query/account-query-context';
import { activeAttendanceRefreshInterval } from '@/core/query/attendance-refresh-policy';
import { mergeProgressiveItemsById } from '@/core/query/progressive-page';
import { useRouteFocus } from '@/core/query/use-route-focus';

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
    queryFn: ({ pageParam, signal }) => withAccountQueryContext(
      signal,
      (context) => loadManagerRoster(tripId!, normalizedSearch, pageParam, context),
    ),
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
    queryFn: ({ signal }) => withAccountQueryContext(
      signal,
      (context) => loadManagerPassenger(tripId!, passengerId!, context),
    ),
    enabled: Boolean(accountKey && tripId && passengerId),
    staleTime: 15_000,
  });
}

export function useManagerAttendanceSessions(tripId: string | null) {
  const queryClient = useQueryClient();
  const accountKey = useManagerAccountKey();
  const routeFocused = useRouteFocus();
  const queryKey = useMemo(
    () => ['manager-attendance-sessions', accountKey, tripId] as const,
    [accountKey, tripId],
  );
  return useQuery({
    queryKey,
    queryFn: ({ signal }) => withAccountQueryContext(
      signal,
      (context) => loadManagerAttendanceSessions(tripId!, context, (items) => {
        queryClient.setQueryData<Awaited<ReturnType<typeof loadManagerAttendanceSessions>>>(
          queryKey,
          (current) => ({
            items: mergeProgressiveItemsById(items, current?.items),
          }),
        );
      }),
    ),
    enabled: Boolean(accountKey && tripId),
    staleTime: 5_000,
    refetchInterval: (query) => activeAttendanceRefreshInterval({
      hasActiveSession: Boolean(
        query.state.data?.items.some((session) => session.status === 'active'),
      ),
      error: query.state.error,
      routeFocused,
    }),
    refetchIntervalInBackground: false,
  });
}

export function useManagerAttendanceRoster(
  tripId: string | null,
  sessionId: string | null,
  status: AttendanceRosterStatus,
  enabled: boolean,
) {
  const queryClient = useQueryClient();
  const accountKey = useManagerAccountKey();
  const queryKey = useMemo(
    () => ['manager-attendance-roster', accountKey, tripId, sessionId, status] as const,
    [accountKey, sessionId, status, tripId],
  );
  return useQuery({
    queryKey,
    queryFn: ({ signal }) => withAccountQueryContext(
      signal,
      (context) => loadManagerAttendanceRoster(
        tripId!,
        sessionId!,
        status,
        context,
        (progress) => {
          queryClient.setQueryData<Awaited<ReturnType<typeof loadManagerAttendanceRoster>>>(
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

import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from '@tanstack/react-query';
import { useCallback, useMemo } from 'react';

import { useSessionStore } from '@/core/auth/session-store';
import { accountNamespace } from '@/core/auth/types';
import { withAccountQueryContext } from '@/core/query/account-query-context';
import { usePersistentQueryHydration } from '@/core/query/use-persistent-query-hydration';

import {
  loadNotifications,
  localNotifications,
  markNotificationRead,
} from '../data/notification-repository';

export function useNotifications(tripId: string | null) {
  const queryClient = useQueryClient();
  const agencyId = useSessionStore((state) => state.session?.principal.agencyId ?? null);
  const accountId = useSessionStore((state) => state.session?.principal.accountId ?? null);
  const accountKey = agencyId && accountId ? accountNamespace({ agencyId, accountId }) : null;
  const queryKey = useMemo(
    () => ['mobile-notifications', tripId, accountKey] as const,
    [accountKey, tripId],
  );
  const loadCachedNotifications = useCallback(async () => {
    const items = await localNotifications(tripId!);
    return {
      pages: [{
        items,
        next_cursor: null,
        unread_count: items.filter((item) => !item.read_at).length,
        offline: true,
      }],
      pageParams: [null],
    };
  }, [tripId]);
  const cacheHydrated = usePersistentQueryHydration({
    accountKey,
    hydrationKey: tripId ? `mobile-notifications:${tripId}` : null,
    queryKey,
    load: loadCachedNotifications,
  });
  const query = useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam, signal }) => withAccountQueryContext(
      signal,
      (context) => loadNotifications(tripId!, pageParam, context),
    ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    enabled: Boolean(accountKey && tripId && cacheHydrated),
  });
  const read = useMutation({
    mutationFn: (notificationId: string) => withAccountQueryContext(
      new AbortController().signal,
      (context) => markNotificationRead(notificationId, tripId!, context),
    ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['mobile-notifications', tripId] }),
  });
  return { ...query, markRead: read.mutate, markingRead: read.isPending };
}

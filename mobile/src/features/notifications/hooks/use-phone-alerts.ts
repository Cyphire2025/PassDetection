import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { AppState } from 'react-native';

import { apiRequest } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';
import { withAccountQueryContext } from '@/core/query/account-query-context';

import { MobileNotificationPageSchema, MobileNotificationReadSchema } from '../api/notification-contracts';

/** Account-wide alerts deliberately need no selected trip or operational grant. */
export function usePhoneAlerts() {
  const client = useQueryClient();
  const session = useSessionStore((state) => state.session);
  const namespace = session ? principalAccountNamespace(session.principal) : null;
  const queryKey = ['phone-alerts', namespace, session?.sessionId ?? null] as const;
  const online = session?.networkMode === 'online';
  const query = useInfiniteQuery({
    queryKey,
    enabled: Boolean(namespace && online && session?.accessToken),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => withAccountQueryContext(signal, (context) => {
      const params = new URLSearchParams({ limit: '100', notification_type: 'gc_alert' });
      if (pageParam) params.set('cursor', pageParam);
      return apiRequest(`/mobile/notifications?${params.toString()}`, {
        schema: MobileNotificationPageSchema, signal: context.signal,
      });
    }),
    getNextPageParam: (page) => page.next_cursor,
  });
  const refresh = query.refetch;
  useEffect(() => {
    const listener = AppState.addEventListener('change', (state) => {
      if (state === 'active' && namespace && online) void refresh();
    });
    return () => listener.remove();
  }, [namespace, online, refresh]);
  const read = useMutation({
    mutationFn: (notificationId: string) => withAccountQueryContext(new AbortController().signal, (context) => {
      if (!online) throw new Error('Connect to mark this alert as read.');
      return apiRequest(`/mobile/notifications/${notificationId}/read`, {
        method: 'POST', body: {}, schema: MobileNotificationReadSchema, signal: context.signal,
      });
    }),
    onSuccess: () => Promise.all([
      client.invalidateQueries({ queryKey }),
      client.invalidateQueries({ queryKey: ['mobile-notifications'] }),
    ]),
  });
  const items = [...new Map((query.data?.pages.flatMap((page) => page.items) ?? [])
    .filter((item) => item.notification_type === 'gc_alert')
    .map((item) => [item.id, item])).values()];
  return { ...query, items, online, markRead: read.mutate, markingRead: read.isPending, readFailed: read.isError };
}

import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import { loadNotifications, markNotificationRead } from '../data/notification-repository';

export function useNotifications(tripId: string | null) {
  const queryClient = useQueryClient();
  const query = useInfiniteQuery({
    queryKey: ['mobile-notifications', tripId],
    queryFn: ({ pageParam }) => loadNotifications(tripId!, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    enabled: Boolean(tripId),
  });
  const read = useMutation({
    mutationFn: (notificationId: string) => markNotificationRead(notificationId, tripId!),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['mobile-notifications', tripId] }),
  });
  return { ...query, markRead: read.mutate, markingRead: read.isPending };
}

"use client";

import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { notificationsApi } from "../api/notifications.api";
import type { NotificationPriority } from "../types";

const CLOSED_REFRESH_INTERVAL_MS = 15_000;
const OPEN_REFRESH_INTERVAL_MS = 5_000;

export const notificationQueryKeys = {
  root: (userId: string) => ["notifications", userId] as const,
  feed: (
    userId: string,
    unreadOnly: boolean,
    priority: NotificationPriority | undefined,
  ) =>
    [
      "notifications",
      userId,
      "feed",
      { unreadOnly, priority: priority ?? null },
    ] as const,
};

export function useNotificationFeed({
  userId,
  isOpen,
  unreadOnly = false,
  priority,
}: {
  userId: string | null | undefined;
  isOpen: boolean;
  unreadOnly?: boolean;
  priority?: NotificationPriority;
}) {
  const scopedUserId = userId ?? "anonymous";
  return useInfiniteQuery({
    queryKey: notificationQueryKeys.feed(
      scopedUserId,
      unreadOnly,
      priority,
    ),
    queryFn: ({ pageParam }) =>
      notificationsApi.feed({
        unreadOnly,
        priority,
        limit: 12,
        cursor: pageParam ?? undefined,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    enabled: Boolean(userId),
    refetchInterval: isOpen
      ? OPEN_REFRESH_INTERVAL_MS
      : CLOSED_REFRESH_INTERVAL_MS,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    refetchOnReconnect: "always",
  });
}

function useInvalidateNotifications(userId: string | null | undefined) {
  const queryClient = useQueryClient();
  return () => {
    if (!userId) return Promise.resolve();
    return queryClient.invalidateQueries({
      queryKey: notificationQueryKeys.root(userId),
    });
  };
}

export function useMarkNotificationRead(
  userId: string | null | undefined,
) {
  const invalidate = useInvalidateNotifications(userId);
  return useMutation({
    mutationFn: notificationsApi.markRead,
    onSettled: invalidate,
  });
}

export function useMarkAllNotificationsRead(
  userId: string | null | undefined,
) {
  const invalidate = useInvalidateNotifications(userId);
  return useMutation({
    mutationFn: notificationsApi.markAllRead,
    onSettled: invalidate,
  });
}

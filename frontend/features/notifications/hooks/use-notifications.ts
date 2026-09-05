"use client";

import { useLiveHistoryFeed } from "@/lib/hooks/use-live-history-feed";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { notificationsApi } from "../api/notifications.api";
import type { NotificationFeedResponse, NotificationPriority } from "../types";

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
  return useLiveHistoryFeed<NotificationFeedResponse>({
    queryKey: notificationQueryKeys.feed(scopedUserId, unreadOnly, priority),
    itemKey: (item) => item.id,
    loadPage: (cursor, signal) =>
      notificationsApi.feed(
        { unreadOnly, priority, limit: 12, cursor },
        signal,
      ),
    enabled: Boolean(userId),
    interval: isOpen ? OPEN_REFRESH_INTERVAL_MS : CLOSED_REFRESH_INTERVAL_MS,
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

export function useMarkNotificationRead(userId: string | null | undefined) {
  const invalidate = useInvalidateNotifications(userId);
  return useMutation({
    mutationFn: notificationsApi.markRead,
    onSettled: invalidate,
  });
}

export function useMarkAllNotificationsRead(userId: string | null | undefined) {
  const invalidate = useInvalidateNotifications(userId);
  return useMutation({
    mutationFn: notificationsApi.markAllRead,
    onSettled: invalidate,
  });
}

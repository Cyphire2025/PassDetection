"use client";

import { useMemo, useState } from "react";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import type { NotificationPriority } from "../types";
import { useMarkAllNotificationsRead, useMarkNotificationRead, useNotificationFeed } from "./use-notifications";

type FeedFilter = "all" | "unread" | "urgent" | "high";

export function useNotificationCenter() {
  const user = useAuthStore(selectUser);
  const [isOpen, setIsOpen] = useState(false);
  const [filter, setFilter] = useState<FeedFilter>("all");
  const priority: NotificationPriority | undefined = filter === "urgent" || filter === "high" ? filter : undefined;
  const feed = useNotificationFeed({ userId: user?.id, isOpen, unreadOnly: filter === "unread", priority });
  const markRead = useMarkNotificationRead(user?.id);
  const markAllRead = useMarkAllNotificationsRead(user?.id);
  const notifications = useMemo(() => feed.data?.pages.flatMap((page) => page.items) ?? [], [feed.data]);
  const unreadCount = feed.data?.pages[0]?.unread_count ?? 0;
  return { isOpen, setIsOpen, filter, setFilter, feed, notifications, markRead, markAllRead, unreadCount };
}

export type NotificationCenter = ReturnType<typeof useNotificationCenter>;

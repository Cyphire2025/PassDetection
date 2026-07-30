"use client";

import Link from "next/link";
import {
  Bell,
  Check,
  CheckCheck,
  ChevronRight,
  RefreshCw,
  X,
} from "lucide-react";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Badge, Button } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { formatRelativeTime } from "@/lib/utils/format";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotificationFeed,
} from "../hooks/use-notifications";
import type {
  NotificationPriority,
  OperationalNotification,
} from "../types";
import {
  notificationTargetRoute,
  readNotificationMetadata,
} from "../utils/notification-navigation";

type FeedFilter = "all" | "unread" | "urgent" | "high";

const FEED_FILTERS: ReadonlyArray<{
  value: FeedFilter;
  label: string;
}> = [
  { value: "all", label: "All" },
  { value: "unread", label: "Unread" },
  { value: "urgent", label: "Critical" },
  { value: "high", label: "High" },
];

export function NotificationBell() {
  const user = useAuthStore(selectUser);
  const [isOpen, setIsOpen] = useState(false);
  const [filter, setFilter] = useState<FeedFilter>("all");
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const unreadOnly = filter === "unread";
  const priority: NotificationPriority | undefined =
    filter === "urgent" || filter === "high" ? filter : undefined;
  const feed = useNotificationFeed({
    userId: user?.id,
    isOpen,
    unreadOnly,
    priority,
  });
  const markRead = useMarkNotificationRead(user?.id);
  const markAllRead = useMarkAllNotificationsRead(user?.id);

  const notifications = useMemo(
    () => feed.data?.pages.flatMap((page) => page.items) ?? [],
    [feed.data],
  );
  const unreadCount = feed.data?.pages[0]?.unread_count ?? 0;

  useEffect(() => {
    if (!isOpen) return;
    const frame = window.requestAnimationFrame(() => panelRef.current?.focus());

    const handlePointerDown = (event: PointerEvent) => {
      if (
        containerRef.current
        && !containerRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setIsOpen(false);
        triggerRef.current?.focus();
        return;
      }
      const panel = panelRef.current;
      if (event.key !== "Tab" || !panel) return;

      const focusable = Array.from(
        panel.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => !element.hasAttribute("hidden"));
      if (focusable.length === 0) {
        event.preventDefault();
        panel.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (
        event.shiftKey
        && (document.activeElement === first || document.activeElement === panel)
      ) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  function closePanel() {
    setIsOpen(false);
    triggerRef.current?.focus();
  }

  return (
    <div ref={containerRef} className="relative">
      <Button
        ref={triggerRef}
        type="button"
        variant="ghost"
        size="icon"
        className="relative h-10 w-10 text-slate-500 hover:text-slate-900"
        aria-label={`Notifications, ${unreadCount} unread`}
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        aria-controls="dashboard-notification-panel"
        onClick={() => setIsOpen((current) => !current)}
      >
        <Bell className="h-5 w-5" aria-hidden="true" />
        {unreadCount > 0 && (
          <span
            className="absolute right-0.5 top-0.5 flex min-h-4 min-w-4 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold leading-4 text-white ring-2 ring-white"
            aria-hidden="true"
          >
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </Button>
      <span className="sr-only" role="status" aria-live="polite">
        {unreadCount === 1
          ? "1 unread notification"
          : `${unreadCount} unread notifications`}
      </span>

      {isOpen && (
        <div
          ref={panelRef}
          id="dashboard-notification-panel"
          role="dialog"
          aria-modal="true"
          aria-label="Notifications"
          tabIndex={-1}
          className="fixed inset-x-2 top-[66px] z-50 max-h-[calc(100dvh-74px)] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl outline-none sm:absolute sm:inset-x-auto sm:right-0 sm:top-12 sm:w-[min(26rem,calc(100vw-2rem))]"
        >
          <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h2 className="font-semibold text-slate-950">Notifications</h2>
                {feed.isFetching && !feed.isLoading && (
                  <RefreshCw
                    className="h-3.5 w-3.5 animate-spin text-slate-400"
                    aria-label="Refreshing notifications"
                  />
                )}
              </div>
              <p className="text-xs text-slate-500">
                Account-scoped operational updates
              </p>
            </div>
            <div className="flex items-center gap-1">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                leftIcon={
                  <CheckCheck className="h-3.5 w-3.5" aria-hidden="true" />
                }
                disabled={unreadCount === 0 || markAllRead.isPending}
                isLoading={markAllRead.isPending}
                onClick={() => {
                  markAllRead.reset();
                  markAllRead.mutate();
                }}
              >
                Mark all read
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                aria-label="Close notifications"
                onClick={closePanel}
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
          </div>

          <div
            className="flex gap-1 overflow-x-auto border-b border-slate-100 px-3 py-2"
            aria-label="Notification filters"
          >
            {FEED_FILTERS.map((option) => (
              <button
                key={option.value}
                type="button"
                aria-pressed={filter === option.value}
                className={`shrink-0 rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                  filter === option.value
                    ? "bg-blue-600 text-white"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200 hover:text-slate-900"
                }`}
                onClick={() => setFilter(option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>

          {(markRead.isError || markAllRead.isError) && (
            <div
              role="alert"
              className="border-b border-red-100 bg-red-50 px-4 py-2 text-xs text-red-700"
            >
              {markAllRead.isError
                ? "Not all notifications could be marked as read. The list is being refreshed; please try again."
                : "That notification could not be marked as read. The list is being refreshed; please try again."}
            </div>
          )}

          <div className="max-h-[min(34rem,calc(100dvh-12rem))] overflow-y-auto">
            {feed.isLoading ? (
              <NotificationSkeletons />
            ) : feed.isError ? (
              <div className="space-y-3 px-4 py-8 text-center">
                <p role="alert" className="text-sm text-red-700">
                  Notifications could not be loaded.
                </p>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={() => void feed.refetch()}
                >
                  Try again
                </Button>
              </div>
            ) : notifications.length > 0 ? (
              <ol className="divide-y divide-slate-100">
                {notifications.map((notification) => (
                  <NotificationRow
                    key={notification.id}
                    notification={notification}
                    isMarkingRead={
                      markRead.isPending && markRead.variables === notification.id
                    }
                    onOpen={() => {
                      if (!notification.is_read) {
                        markRead.reset();
                        markRead.mutate(notification.id);
                      }
                      setIsOpen(false);
                    }}
                    onMarkRead={() => {
                      markRead.reset();
                      markRead.mutate(notification.id);
                    }}
                  />
                ))}
              </ol>
            ) : (
              <div className="px-6 py-10 text-center">
                <span className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-slate-500">
                  <Check className="h-5 w-5" aria-hidden="true" />
                </span>
                <h3 className="mt-3 text-sm font-semibold text-slate-900">
                  Nothing needs attention
                </h3>
                <p className="mt-1 text-xs text-slate-500">
                  New owner-scoped operational updates will appear here.
                </p>
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 bg-slate-50 px-4 py-3">
            {feed.hasNextPage ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                isLoading={feed.isFetchingNextPage}
                onClick={() => void feed.fetchNextPage()}
              >
                Load older
              </Button>
            ) : (
              <span className="text-xs text-slate-500">Latest updates shown</span>
            )}
            <div className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1">
              <Link
                href={ROUTES.dashboard.emailIntegrations as never}
                className="text-xs font-medium text-slate-600 hover:text-slate-900 hover:underline"
                onClick={closePanel}
              >
                Notification settings
              </Link>
              <Link
                href={ROUTES.dashboard.emailIntegrationsInbox as never}
                className="inline-flex items-center gap-1 text-sm font-medium text-blue-700 hover:text-blue-800 hover:underline"
                onClick={closePanel}
              >
                Open inbox
                <ChevronRight className="h-4 w-4" aria-hidden="true" />
              </Link>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function NotificationRow({
  notification,
  isMarkingRead,
  onOpen,
  onMarkRead,
}: {
  notification: OperationalNotification;
  isMarkingRead: boolean;
  onOpen: () => void;
  onMarkRead: () => void;
}) {
  const target = notificationTargetRoute(notification);
  const account =
    readNotificationMetadata(notification.metadata, "account_email")
    ?? readNotificationMetadata(notification.metadata, "email_address");
  const provider = readNotificationMetadata(notification.metadata, "provider");
  const group = readNotificationMetadata(notification.metadata, "group_name");

  return (
    <li
      className={`flex gap-2 px-3 py-3 ${
        notification.is_read ? "bg-white" : "bg-blue-50/50"
      }`}
    >
      <div className="min-w-0 flex-1">
        {target ? (
          <Link
            href={target as never}
            className="block rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
            onClick={onOpen}
          >
            <NotificationContent
              notification={notification}
              account={account}
              provider={provider}
              group={group}
            />
          </Link>
        ) : (
          <NotificationContent
            notification={notification}
            account={account}
            provider={provider}
            group={group}
          />
        )}
      </div>
      {!notification.is_read && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0"
          aria-label={`Mark ${notification.title} as read`}
          isLoading={isMarkingRead}
          onClick={onMarkRead}
        >
          <Check className="h-4 w-4" aria-hidden="true" />
        </Button>
      )}
    </li>
  );
}

function NotificationContent({
  notification,
  account,
  provider,
  group,
}: {
  notification: OperationalNotification;
  account: string | null;
  provider: string | null;
  group: string | null;
}) {
  return (
    <>
      <div className="flex flex-wrap items-center gap-1.5">
        <PriorityBadge priority={notification.priority} />
        <span className="text-[11px] font-medium text-slate-500">
          {formatCategory(notification.category)}
        </span>
        {!notification.is_read && <span className="sr-only">Unread</span>}
      </div>
      <h3 className="mt-1 break-words text-sm font-semibold text-slate-950">
        {notification.title}
      </h3>
      <p className="mt-0.5 line-clamp-2 break-words text-xs leading-5 text-slate-600">
        {notification.message}
      </p>
      {(account || provider || group) && (
        <p className="mt-1 truncate text-[11px] text-slate-500">
          {[provider && formatCategory(provider), account, group]
            .filter(Boolean)
            .join(" · ")}
        </p>
      )}
      <time
        dateTime={notification.created_at}
        title={notification.created_at}
        className="mt-1 block text-[11px] text-slate-400"
      >
        {formatRelativeTime(notification.created_at)}
      </time>
    </>
  );
}

function PriorityBadge({ priority }: { priority: string }) {
  const normalized = priority.toLowerCase();
  const variant =
    normalized === "critical" || normalized === "urgent"
      ? "destructive"
      : normalized === "high"
        ? "warning"
        : normalized === "medium"
          ? "secondary"
          : "outline";
  return (
    <Badge variant={variant} className="px-2 py-0 text-[10px]">
      {formatCategory(priority)}
    </Badge>
  );
}

function NotificationSkeletons() {
  return (
    <div aria-label="Loading notifications">
      {Array.from({ length: 4 }, (_, index) => (
        <div key={index} className="space-y-2 border-b border-slate-100 px-4 py-4">
          <div className="h-4 w-20 animate-pulse rounded bg-slate-200" />
          <div className="h-4 w-4/5 animate-pulse rounded bg-slate-200" />
          <div className="h-3 w-full animate-pulse rounded bg-slate-100" />
        </div>
      ))}
    </div>
  );
}

function formatCategory(value: string) {
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

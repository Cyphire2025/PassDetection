"use client";

import { Button } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { Check, CheckCheck, ChevronRight, RefreshCw, X } from "lucide-react";
import Link from "next/link";
import type { KeyboardEventHandler, RefObject } from "react";
import type { NotificationCenter } from "../hooks/use-notification-center";
import { NotificationRow } from "./notification-row";

const FEED_FILTERS = [
  { value: "all", label: "All" },
  { value: "unread", label: "Unread" },
  { value: "urgent", label: "Critical" },
  { value: "high", label: "High" },
] as const;

export function NotificationPanel({ center, panelRef, onKeyDown, closePanel }: {
  center: NotificationCenter;
  panelRef: RefObject<HTMLDivElement | null>;
  onKeyDown: KeyboardEventHandler<HTMLDivElement>;
  closePanel: () => void;
}) {
  const { filter, setFilter, feed, notifications, markRead, markAllRead, unreadCount, setIsOpen } = center;
  return (
    <div
      ref={panelRef}
      onKeyDown={onKeyDown}
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
                  markRead.isPending &&
                  markRead.variables === notification.id
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
        {feed.isBrowsingHistory && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => void feed.returnToLatest()}
          >
            Return to latest
          </Button>
        )}
        {feed.historyError && (
          <p role="alert" className="px-4 py-2 text-sm text-red-700">
            Older items could not be loaded. Try loading more again.
          </p>
        )}
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
          <span className="text-xs text-slate-500">
            Latest updates shown
          </span>
        )}
        <div className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1">
          <Link
            href={ROUTES.dashboard.emailIntegrations}
            className="text-xs font-medium text-slate-600 hover:text-slate-900 hover:underline"
            onClick={closePanel}
          >
            Notification settings
          </Link>
          <Link
            href={ROUTES.dashboard.emailIntegrationsInbox}
            className="inline-flex items-center gap-1 text-sm font-medium text-blue-700 hover:text-blue-800 hover:underline"
            onClick={closePanel}
          >
            Open inbox
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
          </Link>
        </div>
      </div>
    </div>
  );
}

function NotificationSkeletons() {
  return (
    <div aria-label="Loading notifications">
      {Array.from({ length: 4 }, (_, index) => (
        <div
          key={index}
          className="space-y-2 border-b border-slate-100 px-4 py-4"
        >
          <div className="h-4 w-20 animate-pulse rounded bg-slate-200" />
          <div className="h-4 w-4/5 animate-pulse rounded bg-slate-200" />
          <div className="h-3 w-full animate-pulse rounded bg-slate-100" />
        </div>
      ))}
    </div>
  );
}


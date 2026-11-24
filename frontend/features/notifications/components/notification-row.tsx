"use client";

import { Badge, Button } from "@/components/ui";
import { formatRelativeTime } from "@/lib/utils/format";
import { Check } from "lucide-react";
import Link from "next/link";
import type { OperationalNotification } from "../types";
import { notificationTargetRoute, readNotificationMetadata } from "../utils/notification-navigation";

export function NotificationRow({
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
    readNotificationMetadata(notification.metadata, "account_email") ??
    readNotificationMetadata(notification.metadata, "email_address");
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
            href={target}
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

function formatCategory(value: string) {
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

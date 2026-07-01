"use client";

import { Bell, Check } from "lucide-react";
import { EmptyState, PageHeader } from "@/components/shared";
import { Button, Card, CardContent, Skeleton } from "@/components/ui";
import { formatDateTime } from "@/lib/utils/format";
import { useMarkNotificationRead, useNotifications } from "@/features/operations/hooks/use-operations";

export default function NotificationsPage() {
  const { data, isLoading, error } = useNotifications(false);
  const markRead = useMarkNotificationRead();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Notifications" description="Agency alerts for client submissions and processing events." />
      {error && <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">Notifications are unavailable for this account.</div>}
      {isLoading ? (
        <div className="grid gap-3">{Array.from({ length: 5 }).map((_, index) => <Skeleton key={index} className="h-24 w-full" />)}</div>
      ) : !data || data.length === 0 ? (
        <EmptyState icon={<Bell className="h-5 w-5" />} title="No notifications" description="New client submissions will create notifications here." />
      ) : (
        <div className="grid gap-3">
          {data.map((notification) => (
            <Card key={notification.id} className={notification.is_read ? "bg-white" : "border-blue-200 bg-blue-50/40"}>
              <CardContent className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div className="font-semibold text-slate-900">{notification.title}</div>
                  <div className="mt-1 text-sm text-slate-600">{notification.message}</div>
                  <div className="mt-2 text-xs text-slate-400">{formatDateTime(notification.created_at)}</div>
                </div>
                {!notification.is_read && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-2"
                    disabled={markRead.isPending}
                    onClick={() => markRead.mutate(notification.id)}
                  >
                    <Check className="h-4 w-4" />
                    Mark Read
                  </Button>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

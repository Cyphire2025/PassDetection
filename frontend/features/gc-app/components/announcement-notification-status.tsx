"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { getAnnouncementNotificationStatus } from "../api/announcement-notification-status.api";
import { formatGcDateTime } from "../utils";

export function AnnouncementNotificationStatusPanel({ agencyId, groupId, announcementId, version }: {
  agencyId: string | null; groupId: string; announcementId: string; version: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const query = useQuery({
    queryKey: ["gc-app", agencyId, groupId, "announcement-notification-status", announcementId, version],
    queryFn: ({ signal }) => getAnnouncementNotificationStatus(agencyId, groupId, announcementId, signal),
    enabled: expanded,
    refetchInterval: expanded ? 15_000 : false,
    retry: false,
  });
  const data = query.data;
  return <details className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3" onToggle={(event) => setExpanded(event.currentTarget.open)}>
    <summary className="cursor-pointer text-sm font-medium text-slate-800">Notification delivery status</summary>
    {expanded && <div className="mt-3 space-y-3 text-xs text-slate-600">
      <p>Publishing makes the announcement available in the app. Provider confirmation records the notification handoff; it does not prove that the phone displayed a banner.</p>
      {query.isError && <p role="alert" className="text-red-700">Notification status could not be loaded. Delivery is unknown; refresh to check again.</p>}
      {query.isPending && <p role="status">Checking notification delivery…</p>}
      {data && <>
        {!data.provider_enabled && <p role="status" className="rounded-md bg-amber-100 p-2 text-amber-900">Phone notifications are disabled on the server. The announcement can still appear inside the app.</p>}
        <h4 className="font-semibold text-slate-800">Recipients</h4>
        <Counts items={[
          ["Total recipients", data.recipient_counts.total], ["Queued recipients", data.recipient_counts.queued],
          ["Recorded missing device registrations", data.recipient_counts.no_active_registration],
          ["Recipients with provider confirmation", data.recipient_counts.sent], ["Read in app", data.recipient_counts.read],
          ["Failed recipients", data.recipient_counts.failed], ["Cancelled recipients", data.recipient_counts.cancelled],
        ]} />
        <h4 className="font-semibold text-slate-800">Device deliveries</h4>
        <Counts items={[
          ["Total device deliveries", data.device_delivery_counts.total], ["Submitting", data.device_delivery_counts.submitting],
          ["Waiting to retry", data.device_delivery_counts.retry], ["Awaiting provider confirmation", data.device_delivery_counts.receipt_pending],
          ["Confirmed by provider", data.device_delivery_counts.delivered], ["Failed device deliveries", data.device_delivery_counts.failed],
          ["Cancelled device deliveries", data.device_delivery_counts.cancelled],
        ]} />
        {data.failures.length > 0 && <ul className="list-inside list-disc">{data.failures.map((failure) => <li key={`${failure.scope}:${failure.code}`}>
          {failure.code === "no_active_registration" ? "No registered, authorized device is available" : failure.code.replace(/_/g, " ")}: {failure.count} ({failure.scope === "device" ? "device deliveries" : "recipients"})
        </li>)}</ul>}
        <p>Checked {formatGcDateTime(data.checked_at)}</p>
      </>}
      <Button type="button" size="sm" variant="secondary" isLoading={query.isFetching} onClick={() => void query.refetch()}>Refresh notification status</Button>
    </div>}
  </details>;
}

function Counts({ items }: { items: Array<[string, number]> }) {
  return <dl className="grid grid-cols-1 gap-1 sm:grid-cols-2">{items.map(([label, count]) => <div key={label} className="flex justify-between gap-3"><dt>{label}</dt><dd className="font-semibold text-slate-900">{count}</dd></div>)}</dl>;
}

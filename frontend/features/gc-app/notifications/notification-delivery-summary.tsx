"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button, Card, CardContent } from "@/components/ui";
import { GcAlert } from "../components/gc-app-feedback";
import { formatGcDateTime } from "../utils";
import { notificationsApi } from "./notifications.api";
import type { NotificationBatch } from "./notification-types";

export function NotificationDeliverySummary({ agencyId, batch }: { agencyId: string; batch: NotificationBatch }) {
  const query = useQuery({
    queryKey: ["gc-app", agencyId, "notifications", "batch", batch.id],
    queryFn: ({ signal }) => notificationsApi.getBatch(agencyId, batch.id, signal),
    initialData: batch,
    refetchInterval: 15_000,
    refetchIntervalInBackground: false,
    retry: false,
  });
  const current = query.data;
  const [now, setNow] = useState(() => Date.now());
  const expired = now >= Date.parse(current.expires_at);
  useEffect(() => {
    if (expired) return;
    const timer = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(timer);
  }, [expired]);
  const recipients = current.recipient_counts;
  const devices = current.device_delivery_counts;
  return <Card><CardContent className="space-y-4 p-5">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-semibold text-slate-900">Delivery summary</h2><p className="mt-1 break-words text-sm text-slate-600">{current.title} · Sent {formatGcDateTime(current.created_at)}</p></div><Button type="button" variant="secondary" size="sm" isLoading={query.isFetching} onClick={() => void query.refetch()}>Refresh delivery status</Button></div>
    {query.isError && <GcAlert message="Delivery status could not be refreshed. The last loaded counts are shown." />}
    <p className="text-xs text-slate-500">Provider acceptance confirms a handoff. It does not prove a banner appeared on a phone. Read counts refer to the notification inside the app.</p>
    {!current.provider_enabled && <GcAlert tone="info" message="Phone delivery is disabled on the server." />}
    <div><h3 className="mb-2 text-sm font-semibold text-slate-800">Recipients</h3><Counts items={[
      ["Total recipients", recipients.total], [expired ? "Expired unsent recipients" : "Queued", recipients.queued], ["Accepted notification", recipients.sent],
      ["Read in app", recipients.read], ["No active device registration", recipients.no_active_registration],
      ["Failed", recipients.failed], ["Cancelled", recipients.cancelled], ["Unknown outcome", recipients.unknown],
    ]} /></div>
    <div><h3 className="mb-2 text-sm font-semibold text-slate-800">Devices</h3><Counts items={[
      ["Total device deliveries", devices.total], ["Submitting", devices.submitting], [expired ? "Expired unsent retries" : "Waiting to retry", devices.retry],
      ["Awaiting provider receipt", devices.receipt_pending], ["Provider accepted; phone display unconfirmed", devices.provider_accepted],
      ["Provider receipt received; phone display unconfirmed", devices.delivered], ["Failed device deliveries", devices.failed],
      ["Cancelled device deliveries", devices.cancelled], ["Unknown send outcome", devices.unknown],
    ]} /></div>
    {(recipients.unknown > 0 || devices.unknown > 0) && <GcAlert tone="info" message="Unknown outcomes are not automatically resent. A deliberate Send again creates a separate alert and can duplicate an alert already received." />}
    {expired && <GcAlert tone="info" message="Delivery window ended — remaining queued attempts will not be sent. Provider acceptance and unknown outcomes remain recorded as reported." />}
    <p className="text-xs text-slate-500">Delivery window {expired ? "ended" : "ends"} {formatGcDateTime(current.expires_at)}.</p>
  </CardContent></Card>;
}

function Counts({ items }: { items: Array<[string, number]> }) {
  return <dl className="grid gap-x-6 gap-y-2 text-xs sm:grid-cols-2">{items.map(([label, count]) => <div key={label} className="flex justify-between gap-3"><dt className="text-slate-600">{label}</dt><dd className="font-semibold text-slate-900">{count}</dd></div>)}</dl>;
}

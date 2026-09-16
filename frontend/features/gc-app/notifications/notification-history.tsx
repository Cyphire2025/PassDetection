"use client";

import { useQuery } from "@tanstack/react-query";
import { Clock3, FileClock, Users } from "lucide-react";
import { Badge, Button, Card, Skeleton } from "@/components/ui";
import { GcAlert } from "../components/gc-app-feedback";
import { formatGcDateTime } from "../utils";
import { notificationsApi } from "./notifications.api";
import { CursorPagination, useCursorPage } from "./notification-pagination";
import type { NotificationBatch } from "./notification-types";

export function NotificationHistory({ agencyId, actorId, onView }: {
  agencyId: string;
  actorId: string;
  onView: (batch: NotificationBatch) => void;
}) {
  const pagination = useCursorPage();
  const history = useQuery({
    queryKey: ["gc-app", agencyId, "notifications", "batches", "history", actorId, pagination.cursor],
    queryFn: ({ signal }) => notificationsApi.listBatches(agencyId, pagination.cursor, signal),
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    retry: false,
  });
  const batches = history.data?.items ?? [];

  return <Card className="overflow-hidden border-slate-200/80 shadow-sm">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-slate-50/70 px-5 py-4 sm:px-6">
      <div className="flex items-center gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-blue-100 bg-blue-50 text-blue-600"><FileClock className="h-5 w-5" aria-hidden="true" /></span>
        <div><h3 className="font-semibold text-slate-950">Send log</h3><p className="mt-0.5 text-xs text-slate-500">Newest first · One entry for each send</p></div>
      </div>
      <Badge variant="outline" className="bg-white">Read-only history</Badge>
    </header>
    {history.isError && <div className="p-5 pb-0"><GcAlert message={history.data
      ? "History could not be refreshed. Previously loaded records are shown; refresh before relying on delivery counts."
      : "Notification history could not be loaded. Select Refresh to try again."} /></div>}
    {history.isPending ? <div role="status" aria-label="Loading notification history" className="space-y-3 p-5">
      {[0, 1, 2].map((row) => <Skeleton key={row} className="h-24 w-full rounded-xl" />)}
      <p className="text-sm text-slate-500">Loading notification history…</p>
    </div> : history.isSuccess && batches.length === 0 ? <div className="flex flex-col items-center px-6 py-14 text-center">
      <span className="mb-4 rounded-2xl bg-slate-100 p-4 text-slate-400"><Clock3 className="h-7 w-7" aria-hidden="true" /></span>
      <h4 className="font-semibold text-slate-900">{pagination.page === 1 ? "No notifications sent yet" : "No more sends on this page"}</h4>
      <p className="mt-2 max-w-sm text-sm leading-6 text-slate-500">{pagination.page === 1
        ? "Once you send a notification, its message, audience and delivery progress will appear here."
        : "Return to the previous page or refresh to check for updated records."}</p>
    </div> : batches.length > 0 ? <>
      <div className="hidden overflow-x-auto lg:block">
        <table className="w-full table-fixed text-left text-sm">
          <caption className="sr-only">Notification sends and provider status</caption>
          <thead className="border-b border-slate-200 bg-slate-50/50 text-[11px] font-semibold uppercase tracking-wide text-slate-500"><tr>
            <th scope="col" className="w-[32%] px-6 py-3">Notification</th>
            <th scope="col" className="w-[22%] px-4 py-3">Audience</th>
            <th scope="col" className="w-[14%] px-4 py-3">Recipients</th>
            <th scope="col" className="w-[21%] px-4 py-3">Provider status</th>
            <th scope="col" className="w-[11%] px-4 py-3"><span className="sr-only">Details</span></th>
          </tr></thead>
          <tbody className="divide-y divide-slate-100">{batches.map((batch) => <tr key={batch.id} className="align-top transition-colors hover:bg-slate-50/60">
            <td className="px-6 py-5"><MessageSnapshot batch={batch} /></td>
            <td className="px-4 py-5"><AudienceSnapshot batch={batch} /></td>
            <td className="px-4 py-5"><RecipientCount batch={batch} /></td>
            <td className="px-4 py-5"><ProviderCounts batch={batch} /></td>
            <td className="px-4 py-5"><Button type="button" size="sm" variant="ghost" className="text-blue-700" aria-label={`View delivery details for ${batch.title}`} onClick={() => onView(batch)}>Details</Button></td>
          </tr>)}</tbody>
        </table>
      </div>
      <div className="space-y-3 p-4 lg:hidden">{batches.map((batch) => <article key={batch.id} aria-label={`Sent notification: ${batch.title}`} className="space-y-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <MessageSnapshot batch={batch} />
        <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-4 border-t border-slate-100 pt-3">
          <div><p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-slate-400">Audience</p><AudienceSnapshot batch={batch} /></div>
          <div><p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-slate-400">Recipients</p><RecipientCount batch={batch} /></div>
        </div>
        <div><p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-slate-400">Provider status</p><ProviderCounts batch={batch} /></div>
        <Button type="button" size="sm" variant="secondary" className="w-full" onClick={() => onView(batch)}>View delivery details</Button>
      </article>)}</div>
    </> : null}
    <div className="px-5 pb-5 sm:px-6"><CursorPagination {...pagination}
      nextCursor={history.isError ? null : history.data?.next_cursor ?? null}
      itemCount={history.data?.items.length}
      disabled={history.isFetching}
      onRefresh={() => void history.refetch()} />
      <p className="mt-3 text-xs leading-5 text-slate-500">Provider counts refer to device deliveries. Provider acceptance does not confirm that a notification appeared on a phone. Open Details for the full delivery breakdown.</p>
    </div>
  </Card>;
}

function MessageSnapshot({ batch }: { batch: NotificationBatch }) {
  return <div className="min-w-0 space-y-1.5">
    <p className="break-words font-semibold text-slate-900">{batch.title}</p>
    <p className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-600">{batch.body}</p>
    <p className="flex items-center gap-1.5 pt-1 text-xs text-slate-500"><Clock3 className="h-3.5 w-3.5 shrink-0" aria-hidden="true" /><time dateTime={batch.created_at}>{formatGcDateTime(batch.created_at)}</time></p>
  </div>;
}

function AudienceSnapshot({ batch }: { batch: NotificationBatch }) {
  const names = batch.group_names;
  return <div className="space-y-1.5 text-xs leading-5">
    <p className="font-medium text-slate-800">{batch.audience === "all_active_trips" ? "All active trips at send time" : `${batch.group_ids.length} selected ${batch.group_ids.length === 1 ? "trip" : "trips"}`}</p>
    {names.length > 0 && <details className="text-slate-500">
      <summary className="cursor-pointer break-words rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600">{names.slice(0, 2).join(", ")}{names.length > 2 ? ` +${names.length - 2} more` : ""}</summary>
      <ul className="mt-2 max-h-44 space-y-1 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-2">{names.map((name, index) => <li key={batch.group_ids[index] ?? index} className="break-words">{name}</li>)}</ul>
    </details>}
  </div>;
}

function RecipientCount({ batch }: { batch: NotificationBatch }) {
  return <div className="space-y-1.5"><p className="flex items-center gap-1.5 font-semibold tabular-nums text-slate-900"><Users className="h-3.5 w-3.5 text-slate-400" aria-hidden="true" />{batch.recipient_counts.total}</p><p className="text-xs text-slate-500">{batch.recipient_counts.read} read in app</p></div>;
}

function ProviderCounts({ batch }: { batch: NotificationBatch }) {
  const counts = batch.device_delivery_counts;
  return <div className="flex flex-wrap gap-1.5">
    {!batch.provider_enabled && <Badge variant="warning">Provider currently unavailable</Badge>}
    <Badge variant={counts.provider_accepted > 0 ? "success" : "default"}>{counts.provider_accepted} accepted</Badge>
    {counts.delivered > 0 && <Badge variant="secondary">{counts.delivered} provider receipts</Badge>}
    {counts.failed > 0 && <Badge variant="destructive">{counts.failed} failed</Badge>}
    {counts.unknown > 0 && <Badge variant="warning">{counts.unknown} unknown</Badge>}
    {counts.total === 0 && <span className="text-xs leading-5 text-slate-500">No device deliveries recorded</span>}
  </div>;
}

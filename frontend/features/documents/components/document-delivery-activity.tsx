"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronLeft, ChevronRight, FileText, RefreshCw, Search, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { useDebounce } from "@/hooks/use-debounce";
import { cn } from "@/lib/utils/cn";
import { formatDateTime } from "@/lib/utils/format";
import {
  type DocumentDeliveryActivityFilter,
  type DocumentDeliveryActivityItem,
  type WhatsAppActivityKind,
  whatsappActivityApi,
} from "@/features/whatsapp/api/whatsapp-activity.api";
import { WhatsAppBroadcastMotion } from "@/features/whatsapp/components/whatsapp-broadcast-motion";
import { type DisplayedWhatsAppActivity, whatsappActivitySourceHref } from "@/features/whatsapp/utils/activity-tracking";
import { documentActivityPollInterval, shouldRetryWhatsAppBatchStatus, whatsappBatchHttpStatus } from "@/features/whatsapp/utils/batch-polling";

const PAGE_SIZE = 50;
const FILTERS: { key: DocumentDeliveryActivityFilter; label: string }[] = [
  { key: "all", label: "All PDFs" },
  { key: "queued", label: "Queued" },
  { key: "processing", label: "Sending" },
  { key: "sent", label: "Accepted" },
  { key: "delivered", label: "Delivered" },
  { key: "read", label: "Read" },
  { key: "failed", label: "Failed" },
  { key: "needs_review", label: "Needs review" },
];

const STATUS_LABELS: Record<string, string> = {
  queued: "Queued",
  processing: "Sending",
  submitted: "Accepted by WhatsApp",
  sent: "Sent · awaiting delivery",
  delivered: "Delivered",
  read: "Read",
  failed: "Failed",
  delivery_unknown: "Outcome unknown",
  stalled: "Needs review",
};

function statusClass(status: string) {
  if (status === "failed") return "bg-red-50 text-red-700 ring-red-200";
  if (status === "delivery_unknown" || status === "stalled") return "bg-amber-50 text-amber-800 ring-amber-200";
  if (status === "delivered" || status === "read") return "bg-emerald-50 text-emerald-700 ring-emerald-200";
  if (status === "processing" || status === "submitted" || status === "sent") return "bg-blue-50 text-blue-700 ring-blue-200";
  return "bg-slate-100 text-slate-600 ring-slate-200";
}

export function DocumentDeliveryActivity({ activity, variant, onDismiss }: {
  activity: DisplayedWhatsAppActivity;
  variant: "inline" | "floating";
  onDismiss: (id: string, kind: WhatsAppActivityKind) => void;
}) {
  const queryClient = useQueryClient();
  const detailsId = useId();
  const searchId = useId();
  const [expanded, setExpanded] = useState(false);
  const [filter, setFilter] = useState<DocumentDeliveryActivityFilter>("all");
  const [search, setSearch] = useState("");
  const querySearch = useDebounce(search.trim(), 300);
  const [page, setPage] = useState({ key: "", offset: 0 });
  const [refreshing, setRefreshing] = useState(false);
  const pageKey = `${filter}\u0000${querySearch}`;
  const offset = page.key === pageKey ? page.offset : 0;
  const isSearching = querySearch !== search.trim();
  const isRunning = activity.queued > 0;
  const needsAttention = activity.failed + activity.delivery_unknown > 0;
  const statusCounts = activity.status_counts;
  const counts: Record<DocumentDeliveryActivityFilter, number> = {
    all: activity.total,
    queued: statusCounts?.queued ?? activity.queued,
    processing: statusCounts?.processing ?? 0,
    sent: activity.sent,
    delivered: (statusCounts?.delivered ?? 0) + (statusCounts?.read ?? 0),
    read: statusCounts?.read ?? 0,
    failed: activity.failed,
    needs_review: activity.delivery_unknown,
  };
  const processed = Math.min(activity.total, Math.max(0, activity.total - activity.queued));
  const percent = activity.total ? Math.round(processed / activity.total * 100) : 0;
  const pollInterval = documentActivityPollInterval(activity.queued, statusCounts, activity.startedAt);
  const deliveries = useQuery({
    queryKey: ["whatsapp", "activities", "document", activity.activity_id, "deliveries", filter, querySearch, offset],
    queryFn: ({ signal }) => whatsappActivityApi.documentDeliveries(
      activity.activity_id,
      { status_filter: filter, q: querySearch, offset, limit: PAGE_SIZE },
      signal,
    ),
    enabled: expanded && !isSearching,
    staleTime: 1_000,
    gcTime: 60_000,
    retry: (failureCount, error) => shouldRetryWhatsAppBatchStatus(failureCount, whatsappBatchHttpStatus(error)),
    refetchInterval: expanded && !isSearching ? pollInterval : false,
    refetchIntervalInBackground: false,
  });
  const refetchDeliveries = deliveries.refetch;
  useEffect(() => {
    // A final receipt may reach the summary before the last details poll. Keep
    // expanded rows current even when that receipt stops automatic polling.
    if (expanded && !isSearching && pollInterval === false) {
      void refetchDeliveries({ cancelRefetch: false });
    }
  }, [expanded, isSearching, pollInterval, activity.updated_at, refetchDeliveries]);
  const matchCount = deliveries.data?.total ?? 0;
  const pageLength = deliveries.data?.items.length ?? 0;
  const firstItem = pageLength ? offset + 1 : 0;
  const lastItem = pageLength ? offset + pageLength : 0;
  const selectedLabel = FILTERS.find((item) => item.key === filter)?.label ?? "All PDFs";

  const refresh = async () => {
    setRefreshing(true);
    try {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["whatsapp", "activities", "document", activity.activity_id], exact: true }),
        expanded && !isSearching ? deliveries.refetch() : Promise.resolve(),
      ]);
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <article
      className={cn("bg-white text-slate-950", variant === "floating" ? "overflow-hidden rounded-2xl border border-blue-200 shadow-lg" : "p-4 sm:p-5")}
      aria-label={`${activity.title}: ${activity.sent} accepted of ${activity.total} PDFs`}
    >
      <div className={cn("flex min-w-0 items-start gap-3", variant === "floating" && "touch-none px-4 py-3")}>
        <div className={cn("shrink-0", variant === "floating" ? "w-20" : "w-24 sm:w-32")}>
          <WhatsAppBroadcastMotion compact messageType="document" startedAt={activity.startedAt}
            state={activity.refresh_error ? "reconnecting" : isRunning ? "sending" : needsAttention ? "attention" : "complete"} />
        </div>
        <div className="min-w-0 flex-1 py-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <Link href={whatsappActivitySourceHref(activity) as never} className="text-sm font-semibold hover:text-blue-700 hover:underline">
              {activity.title}
            </Link>
            <span className={cn("inline-flex items-center gap-1.5 text-xs font-medium", activity.refresh_error || needsAttention ? "text-amber-700" : "text-blue-700")}>
              <span className={cn("h-1.5 w-1.5 rounded-full bg-current", isRunning && !activity.refresh_error && "motion-safe:animate-pulse")} aria-hidden="true" />
              {activity.refresh_error ? "Reconnecting" : isRunning ? "Sending documents" : needsAttention ? "Review delivery results" : "Submission complete"}
            </span>
          </div>
          <p className="mt-1 break-words text-sm text-slate-500">{activity.context_label}</p>
          <p className="mt-1 text-xs font-medium tabular-nums text-slate-700" role="status">
            {activity.sent.toLocaleString()} accepted of {activity.total.toLocaleString()} PDFs
            {isRunning ? ` · ${activity.queued.toLocaleString()} remaining` : ""}
          </p>
        </div>
        <Button variant="ghost" size="icon" className="shrink-0 text-slate-400" aria-label={`Close ${activity.title} progress`}
          title="Hide progress; sending continues" onClick={() => onDismiss(activity.activity_id, activity.kind)}>
          <X className="h-4 w-4" aria-hidden="true" />
        </Button>
      </div>

      <div className={cn("space-y-3", variant === "floating" && "px-4 pb-4")}
        data-whatsapp-activity-no-drag={variant === "floating" ? "" : undefined}>
        <div>
          <div className="mb-1.5 flex justify-between gap-3 text-xs tabular-nums text-slate-500">
            <span>{processed.toLocaleString()} of {activity.total.toLocaleString()} processed</span>
            <span>{percent}%</span>
          </div>
          <div className="flex h-2 overflow-hidden rounded-full bg-slate-100" role="progressbar"
            aria-label={`${activity.title} processing progress`} aria-valuemin={0} aria-valuemax={Math.max(1, activity.total)}
            aria-valuenow={processed} aria-valuetext={`${processed} of ${activity.total} processed; ${activity.sent} accepted, ${activity.failed} failed, ${activity.delivery_unknown} need review`}>
            {[{ count: activity.sent, color: "bg-blue-600" }, { count: activity.failed, color: "bg-red-500" }, { count: activity.delivery_unknown, color: "bg-amber-400" }].map((segment) => (
              <span key={segment.color} className={cn("h-full motion-safe:transition-[width] motion-safe:duration-500", segment.color)}
                style={{ width: `${activity.total ? Math.min(100, segment.count / activity.total * 100) : 0}%` }} />
            ))}
          </div>
        </div>

        <div className={cn("grid grid-cols-4 gap-2", variant === "inline" && "xl:grid-cols-8")} aria-label="Filter document deliveries">
          {FILTERS.map((item) => (
            <button key={item.key} type="button" aria-pressed={expanded && filter === item.key} aria-controls={detailsId}
              onClick={() => { setFilter(item.key); setExpanded(true); setPage({ key: `${item.key}\u0000${querySearch}`, offset: 0 }); }}
              className={cn("min-w-0 rounded-xl border px-2 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600",
                expanded && filter === item.key ? "border-blue-500 bg-blue-50 ring-1 ring-blue-500" : "border-slate-200 bg-slate-50/70 hover:border-blue-300 hover:bg-blue-50/50")}>
              <span className={cn("block text-[11px] font-medium", item.key === "failed" ? "text-red-700" : item.key === "needs_review" ? "text-amber-700" : "text-slate-500")}>{item.label}</span>
              <span className="mt-1 block text-lg font-semibold tabular-nums">{counts[item.key].toLocaleString()}</span>
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
          <Button variant="ghost" size="sm" aria-expanded={expanded} aria-controls={detailsId} onClick={() => setExpanded((value) => !value)}>
            {expanded ? "Hide delivery details" : "View delivery details"}
            <ChevronDown className={cn("h-4 w-4 transition-transform", expanded && "rotate-180")} aria-hidden="true" />
          </Button>
          <div className="flex flex-wrap items-center gap-2 text-slate-500">
            <span title={formatDateTime(activity.updated_at)}>{activity.refresh_error ? "Live updates interrupted" : pollInterval ? "Updates automatically" : "Refresh for the latest receipts"}</span>
            <Button variant="ghost" size="sm" isLoading={refreshing} onClick={() => void refresh()} aria-label={`Refresh ${activity.title} delivery status`}>
              <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" /> Refresh
            </Button>
          </div>
        </div>
        <p className="text-[11px] leading-5 text-slate-500">
          Accepted means WhatsApp accepted the message request. Delivered and Read confirm later updates.
          Each row represents one assigned PDF, including when travellers share a phone number.
        </p>
        {activity.delivery_unknown > 0 ? (
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
            {activity.delivery_unknown.toLocaleString()} {activity.delivery_unknown === 1 ? "delivery needs" : "deliveries need"} review. An uncertain outcome is not automatically resent.
          </p>
        ) : null}

        {expanded ? (
          <section id={detailsId} aria-label={`${selectedLabel} document deliveries`} className="cursor-auto select-text rounded-xl border border-slate-200">
            <div className="space-y-2 border-b border-slate-100 p-3">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-semibold">{selectedLabel}</h3>
                <span className="text-xs tabular-nums text-slate-500" role="status">
                  {isSearching || deliveries.isFetching ? "Updating…" : `${matchCount.toLocaleString()} matching PDFs`}
                </span>
              </div>
              <label htmlFor={searchId} className="sr-only">Search delivery recipients, numbers or PDF filenames</label>
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" aria-hidden="true" />
                <input id={searchId} value={search} onChange={(event) => setSearch(event.target.value)} maxLength={120}
                  placeholder="Search name, WhatsApp number or PDF" className="h-9 w-full rounded-lg border border-slate-200 bg-white pl-9 pr-9 text-xs outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500" />
                {search ? <button type="button" onClick={() => setSearch("")} aria-label="Clear delivery search" className="absolute right-1 top-1 rounded-md p-1.5 text-slate-500 hover:bg-slate-100"><X className="h-4 w-4" aria-hidden="true" /></button> : null}
              </div>
            </div>
            {deliveries.isError ? (
              <div role="alert" className="space-y-2 border-b border-red-100 bg-red-50 p-3 text-xs text-red-700">
                <p>Delivery details could not be refreshed. {deliveries.data ? "The results below are from the last successful update." : "Try refreshing the delivery status."}</p>
                <Button variant="outline" size="sm" onClick={() => void refresh()}>Try again</Button>
              </div>
            ) : null}
            {deliveries.isPending || isSearching ? (
              <p className="p-5 text-center text-sm text-slate-500" role="status">Loading document deliveries…</p>
            ) : deliveries.data?.items.length ? (
              <ul className={cn("divide-y divide-slate-100 overflow-y-auto overscroll-contain", variant === "floating" ? "max-h-60" : "max-h-80")}
                aria-label="Document delivery results" aria-busy={deliveries.isFetching}>
                {deliveries.data.items.map((item) => <DocumentDeliveryItem key={item.delivery_id} item={item} />)}
              </ul>
            ) : deliveries.data ? (
              <p className="p-5 text-center text-sm text-slate-500">
                {offset > 0 ? "This page is now empty as delivery statuses have changed. Return to the previous page or choose a status above." : "No documents match this status and search."}
              </p>
            ) : null}
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 px-3 py-2 text-xs text-slate-500">
              <span>{deliveries.data ? `${firstItem}–${lastItem} of ${matchCount.toLocaleString()}` : "50 PDFs per page"}</span>
              <div className="flex items-center gap-1">
                <Button variant="ghost" size="sm" disabled={offset === 0 || isSearching} aria-label="Previous delivery page"
                  onClick={() => setPage({ key: pageKey, offset: Math.max(0, offset - PAGE_SIZE) })}><ChevronLeft className="h-4 w-4" aria-hidden="true" /> Previous</Button>
                <Button variant="ghost" size="sm" disabled={!deliveries.data || offset + PAGE_SIZE >= matchCount || isSearching} aria-label="Next delivery page"
                  onClick={() => setPage({ key: pageKey, offset: offset + PAGE_SIZE })}>Next <ChevronRight className="h-4 w-4" aria-hidden="true" /></Button>
              </div>
            </div>
          </section>
        ) : <div id={detailsId} hidden />}
      </div>
    </article>
  );
}

function DocumentDeliveryItem({ item }: { item: DocumentDeliveryActivityItem }) {
  return (
    <li className="space-y-2 p-3 text-xs">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="break-words font-semibold text-slate-900">{item.passenger_name}</p>
          <p className="mt-1 tabular-nums text-slate-500">{item.phone_number}</p>
        </div>
        <span className={cn("rounded-full px-2 py-1 text-[11px] font-medium ring-1 ring-inset", statusClass(item.status))}>
          {STATUS_LABELS[item.status] ?? item.status.replaceAll("_", " ")}
        </span>
      </div>
      <div className="flex items-start gap-1.5 text-slate-600">
        <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span className="break-all">{item.document_filename}</span>
      </div>
      {item.error_message ? (
        <details className="rounded-lg bg-amber-50 px-2.5 py-2 text-amber-900">
          <summary className="cursor-pointer font-medium">View delivery error</summary>
          <p className="mt-2 whitespace-pre-wrap break-words leading-5">{item.error_message}</p>
        </details>
      ) : item.status === "delivery_unknown" || item.status === "stalled" ? (
        <p className="text-amber-800">Delivery needs review before another attempt.</p>
      ) : null}
      <p className="text-[11px] text-slate-400">Updated {formatDateTime(item.status_updated_at)}</p>
    </li>
  );
}

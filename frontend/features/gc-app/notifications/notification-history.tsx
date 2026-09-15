"use client";

import { useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { Badge, Button, Card, CardContent } from "@/components/ui";
import { GcAlert } from "../components/gc-app-feedback";
import { formatGcDateTime } from "../utils";
import { notificationsApi } from "./notifications.api";
import type { NotificationBatch, NotificationDraft } from "./notification-types";

export function NotificationHistory({ agencyId, disabled, onEdit, onResend, onView }: {
  agencyId: string;
  disabled: boolean;
  onEdit: (draft: NotificationDraft) => void;
  onResend: (batch: NotificationBatch) => void;
  onView: (batch: NotificationBatch) => void;
}) {
  const [showSaved, setShowSaved] = useState(false);
  const savedPage = useCursorPage();
  const sentPage = useCursorPage();
  const saved = useQuery({
    queryKey: ["gc-app", agencyId, "notifications", "drafts", savedPage.cursor],
    queryFn: ({ signal }) => notificationsApi.listDrafts(agencyId, savedPage.cursor, signal),
    enabled: showSaved,
    placeholderData: keepPreviousData,
    retry: false,
  });
  const sent = useQuery({
    queryKey: ["gc-app", agencyId, "notifications", "batches", sentPage.cursor],
    queryFn: ({ signal }) => notificationsApi.listBatches(agencyId, sentPage.cursor, signal),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    retry: false,
  });
  return <div className="space-y-4">
    <Card><CardContent className="p-5"><details onToggle={(event) => setShowSaved(event.currentTarget.open)}>
      <summary className="cursor-pointer font-semibold text-slate-900">Saved messages</summary>
      <p className="my-3 text-sm text-slate-500">Open a saved draft or message to edit it. Saving never sends a phone alert.</p>
      {saved.isError && <GcAlert message="Saved messages could not be loaded." />}
      {showSaved && saved.isPending && <p role="status">Loading saved messages…</p>}
      {saved.data?.items.length === 0 && <p className="py-3 text-sm text-slate-500">No saved messages yet.</p>}
      <div className="space-y-3">{saved.data?.items.map((item) => <article key={item.id} aria-label={`Saved message: ${item.title}`} className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-slate-200 p-4">
        <div className="min-w-0 flex-1"><p className="break-words font-medium text-slate-900">{item.title}</p><p className="mt-1 break-words text-sm text-slate-600">{item.body}</p><p className="mt-2 text-xs text-slate-500">Updated {formatGcDateTime(item.updated_at)}</p><Badge variant="secondary">{item.status === "draft" ? "Draft" : "Previously sent"}</Badge></div>
        <Button type="button" size="sm" variant="secondary" disabled={disabled || saved.isPlaceholderData || saved.isError} onClick={() => onEdit(item)}>Edit message</Button>
      </article>)}</div>
      <CursorPagination {...savedPage} nextCursor={saved.data?.next_cursor ?? null} disabled={saved.isFetching} onRefresh={() => void saved.refetch()} />
    </details></CardContent></Card>
    <Card><CardContent className="space-y-4 p-5">
      <div><h2 className="font-semibold text-slate-900">Send history</h2><p className="mt-1 text-sm text-slate-500">Each entry records one deliberate send. Resend opens a new message review before another alert is sent.</p></div>
      {sent.isError && <GcAlert message="Send history could not be refreshed. Check the recorded status before sending again." />}
      {sent.isPending && <p role="status">Loading send history…</p>}
      {sent.data?.items.length === 0 && <p className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">No authored notifications have been sent.</p>}
      {sent.data?.items.map((batch) => <article key={batch.id} aria-label={`Sent notification: ${batch.title}`} className="space-y-3 rounded-xl border border-slate-200 p-4">
        <div><h3 className="break-words font-medium text-slate-900">{batch.title}</h3><p className="mt-1 whitespace-pre-wrap break-words text-sm text-slate-600">{batch.body}</p><p className="mt-2 text-xs text-slate-500">{formatGcDateTime(batch.created_at)} · {batch.audience === "all_active_trips" ? "All active trips at send time" : `${batch.group_ids.length} selected trips`} · {batch.recipient_counts.total} recipients</p></div>
        <div className="flex flex-wrap gap-2"><Button type="button" variant="secondary" size="sm" onClick={() => onView(batch)}>View delivery summary</Button><Button type="button" variant="secondary" size="sm" disabled={disabled || sent.isPlaceholderData || sent.isError} onClick={() => onResend(batch)}>Prepare resend</Button></div>
      </article>)}
      <CursorPagination {...sentPage} nextCursor={sent.data?.next_cursor ?? null} disabled={sent.isFetching} onRefresh={() => void sent.refetch()} />
    </CardContent></Card>
  </div>;
}

function useCursorPage() {
  const [cursors, setCursors] = useState<Array<string | null>>([null]);
  return { cursor: cursors[cursors.length - 1] ?? null, page: cursors.length,
    previous: () => setCursors((values) => values.length > 1 ? values.slice(0, -1) : values),
    next: (cursor: string) => setCursors((values) => [...values, cursor]),
  };
}

function CursorPagination({ page, nextCursor, disabled, previous, next, onRefresh }: {
  page: number; nextCursor: string | null; disabled: boolean; previous: () => void; next: (cursor: string) => void; onRefresh: () => void;
}) {
  return <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-3 text-xs text-slate-500"><span>Page {page}</span><div className="flex gap-2">
    <Button type="button" variant="secondary" size="sm" disabled={disabled} onClick={onRefresh}>Refresh</Button>
    <Button type="button" variant="secondary" size="sm" disabled={disabled || page === 1} onClick={previous}>Previous</Button>
    <Button type="button" variant="secondary" size="sm" disabled={disabled || !nextCursor} onClick={() => { if (nextCursor) next(nextCursor); }}>Next</Button>
  </div></div>;
}

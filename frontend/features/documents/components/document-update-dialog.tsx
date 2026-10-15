"use client";

import { useId, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Send, X } from "lucide-react";
import { Button } from "@/components/ui";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import type { ApiError } from "@/lib/api/client";
import type { DistributionDocumentType } from "@/types/document-distribution.types";
import { documentUpdatesApi, type DocumentUpdateRequest } from "../api/document-updates.api";
import { distributionDocumentLabel } from "../config/document-distribution-lanes";
import { DocumentUpdateStatus, hasPendingDocumentUpdates } from "./document-update-status";

export function DocumentUpdateDialog({ groupId, documentType, broadcastGroupId, onClose }: {
  groupId: string; documentType: DistributionDocumentType; broadcastGroupId?: string; onClose: () => void;
}) {
  const titleId = useId();
  const textId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();
  const queryKey = ["document-update-preview", groupId, documentType, broadcastGroupId ?? "all"];
  const preview = useQuery({ queryKey, queryFn: ({ signal }) => documentUpdatesApi.preview(groupId, documentType, broadcastGroupId, signal), staleTime: 0, refetchInterval: query => hasPendingDocumentUpdates(query.state.data?.recipients) ? 5000 : false });
  const [selected, setSelected] = useState<string[] | null>(null);
  const [content, setContent] = useState("");
  const [search, setSearch] = useState("");
  // Retain the exact request across network uncertainty, so Retry cannot create a second send.
  const [submittedRequest, setSubmittedRequest] = useState<DocumentUpdateRequest | null>(null);
  const send = useMutation({
    mutationFn: (request: DocumentUpdateRequest) => documentUpdatesApi.send(groupId, documentType, request),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["document-update-preview", groupId] }); },
    onError: (error: ApiError) => { if ([400, 403, 404, 409, 422].includes(error.status ?? 0)) setSubmittedRequest(null); },
  });
  const handleKeyDown = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: !send.isPending, onClose });
  const eligible = (preview.data?.recipients ?? []).filter(row => row.eligible);
  const chosen = eligible.filter(row => selected === null || selected.includes(row.passenger_id));
  const numbers = new Set(chosen.map(row => row.phone_number)).size;
  const normalizedSearch = search.trim().toLowerCase();
  const visible = (preview.data?.recipients ?? []).filter(row => `${row.passenger_name} ${row.phone_number ?? ""}`.toLowerCase().includes(normalizedSearch));
  const locked = send.isPending || send.isSuccess || submittedRequest !== null;
  const error = send.error as ApiError | null;
  function submit() {
    if (submittedRequest) { send.mutate(submittedRequest); return; }
    if (!preview.data || !content.trim() || !chosen.length) return;
    const request: DocumentUpdateRequest = { request_id: crypto.randomUUID(), preview_token: preview.data.preview_token,
      passenger_ids: chosen.map(row => row.passenger_id), message_content: content.trim(), broadcast_group_id: broadcastGroupId };
    setSubmittedRequest(request);
    send.mutate(request);
  }
  return <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/50 p-4">
    <div ref={dialogRef} onKeyDown={handleKeyDown} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} className="flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-xl bg-white shadow-xl">
      <div className="flex items-start justify-between gap-4 border-b px-6 py-5">
        <div><h2 id={titleId} className="text-xl font-semibold">Inform / update — {distributionDocumentLabel(documentType)}</h2><p className="mt-2 text-sm text-slate-600">Send a text update without a PDF attachment. Review the message and selected travellers below.</p></div>
        <button type="button" aria-label="Close update preview" disabled={send.isPending} onClick={onClose}><X className="h-5 w-5" /></button>
      </div>
      <div className="space-y-5 overflow-y-auto px-6 py-5">
        {preview.isPending ? <p role="status">Loading eligible travellers…</p> : null}
        {preview.error ? <p role="alert" className="text-red-700">{(preview.error as unknown as ApiError).message || "Could not load the update audience."}</p> : null}
        {preview.data?.configuration_error ? <p role="alert" className="text-amber-800">{preview.data.configuration_error}</p> : null}
        <p className="rounded-lg bg-slate-50 p-3 text-sm">Selected by default: missing documents, failed or unknown sends, and travellers with some documents still unsent. Travellers with all assigned documents confirmed as sent are excluded.</p>
        <div className="grid gap-5 md:grid-cols-2">
          <div><label htmlFor={textId} className="font-medium">Your update message</label><textarea id={textId} value={content} onChange={event => setContent(event.target.value)} maxLength={600} rows={7} disabled={locked} data-dialog-initial-focus className="mt-2 w-full rounded-lg border p-3" placeholder="Write the update you want these travellers to receive." /><p className="text-right text-sm text-slate-500">{content.length}/600</p></div>
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4"><p className="text-xs font-semibold uppercase text-emerald-800">{preview.data?.template_name ?? "pending_v1"} · {preview.data?.template_language ?? "English"}</p><p className="mt-3 whitespace-pre-wrap text-sm leading-6">{`Dear Delegates\n\nGreetings from Global Connect Travels.\n\n${content.trim() || "[Your update message]"}\n\nRegards,\nTeam Global Connect Travels`}</p></div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3"><p className="font-medium">{chosen.length} travellers · {numbers} WhatsApp messages</p><Button variant="secondary" disabled={locked} onClick={() => setSelected(chosen.length === eligible.length ? [] : null)}>{chosen.length === eligible.length ? "Clear selection" : "Select all eligible"}</Button></div>
        <p className="text-sm text-slate-600">A shared WhatsApp number receives this update once. Earlier updates with queued, in-progress or unknown outcomes are excluded to avoid duplicates.</p>
        <input aria-label="Search update recipients" value={search} onChange={event => setSearch(event.target.value)} className="w-full rounded-lg border p-3" placeholder="Search name or WhatsApp number" />
        <div className="max-h-72 overflow-auto rounded-lg border">
          {visible.map(row => <label key={row.passenger_id} className="flex items-start gap-3 border-b p-3 last:border-0">
            <input type="checkbox" aria-label={`Select ${row.passenger_name}`} checked={chosen.some(item => item.passenger_id === row.passenger_id)} disabled={locked || !row.eligible} onChange={event => { const current = chosen.map(item => item.passenger_id); setSelected(event.target.checked ? [...current, row.passenger_id] : current.filter(id => id !== row.passenger_id)); }} className="mt-1" />
            <span className="min-w-0 flex-1"><span className="block font-medium">{row.passenger_name}</span><span className="block text-sm text-slate-600">{row.phone_number ?? "No WhatsApp destination"} · {row.document_count ? `${row.confirmed_count}/${row.document_count} documents confirmed sent` : "No document assigned"}</span>{row.reason ? <span className="block text-sm text-amber-800">{row.reason}</span> : null}<DocumentUpdateStatus recipient={row} /></span>
          </label>)}
          {!preview.isPending && !visible.length ? <p className="p-4 text-sm text-slate-600">No matching travellers.</p> : null}
        </div>
        {error ? <p role="alert" className="text-red-700">{error.message || "Could not confirm the send request."}{submittedRequest ? " Retry to check the same request; this will not create another send." : ""}</p> : null}
        {send.data ? <p role="status" className="rounded-lg bg-emerald-50 p-3 text-emerald-800">{send.data.message}</p> : null}
      </div>
      <div className="flex flex-wrap justify-end gap-3 border-t px-6 py-4">
        <Button variant="secondary" disabled={locked || preview.isFetching} onClick={() => { setSelected(null); send.reset(); void preview.refetch(); }}><RefreshCw className="h-4 w-4" />Refresh preview</Button>
        <Button variant="secondary" disabled={send.isPending} onClick={onClose}>{send.isSuccess ? "Done" : "Cancel"}</Button>
        <Button onClick={submit} isLoading={send.isPending} disabled={send.isSuccess || (!submittedRequest && (!preview.data?.can_send || preview.isFetching || !content.trim() || !chosen.length))}><Send className="h-4 w-4" />{submittedRequest && send.isError ? "Retry same request" : `Send update to ${numbers}`}</Button>
      </div>
    </div>
  </div>;
}

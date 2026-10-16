"use client";

import { useId, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageCircle, RefreshCw, Send, X } from "lucide-react";
import { Button } from "@/components/ui";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import type { ApiError } from "@/lib/api/client";
import { groupUpdatesApi, type GroupUpdateAudience, type GroupUpdateRequest } from "../api/group-updates.api";
import { GroupUpdateAudienceFields, GroupUpdateRecipientRow } from "./group-update-audience";
import { MessageComposerSection } from "./whatsapp-message-composer-ui";
import { parseWhatsAppBoldSegments } from "../utils/whatsapp-formatting";

export function GroupUpdateDialog({ groupId, groupName, onClose }: {
  groupId: string; groupName: string; onClose: () => void;
}) {
  const titleId = useId();
  const textId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();
  const [audience, setAudience] = useState<GroupUpdateAudience>({ submission_status: "all", document_status: "all", document_type: "visa" });
  const preview = useQuery({
    queryKey: ["group-update-preview", groupId, audience],
    queryFn: ({ signal }) => groupUpdatesApi.preview(groupId, audience, signal),
    staleTime: 0,
    refetchInterval: query => query.state.data?.recipients.some(row => ["queued", "processing"].includes(row.latest_update_status ?? "")) ? 5000 : false,
  });
  const [selected, setSelected] = useState<string[] | null>(null);
  const [content, setContent] = useState("");
  const [search, setSearch] = useState("");
  // Keep the same request after a lost response; retry must never send twice.
  const [submittedRequest, setSubmittedRequest] = useState<GroupUpdateRequest | null>(null);
  const send = useMutation({
    mutationFn: (request: GroupUpdateRequest) => groupUpdatesApi.send(groupId, request),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["group-update-preview", groupId] }); },
    onError: (error: ApiError) => {
      if ([400, 403, 404, 409, 422].includes(error.status ?? 0)) setSubmittedRequest(null);
    },
  });
  const handleKeyDown = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: !send.isPending, onClose });
  const rows = preview.data?.recipients ?? [];
  const eligible = rows.filter(row => row.eligible);
  const selectedKeys = selected === null ? null : new Set(selected);
  const chosen = eligible.filter(row => selectedKeys === null || selectedKeys.has(row.audience_key));
  const chosenKeys = new Set(chosen.map(row => row.audience_key));
  const numbers = new Set(chosen.map(row => row.phone_number)).size;
  const normalizedSearch = search.trim().toLowerCase();
  const visible = rows.filter(row => `${row.name} ${row.phone_number ?? ""}`.toLowerCase().includes(normalizedSearch));
  const locked = send.isPending || send.isSuccess || submittedRequest !== null;
  const normalizedContent = content.replace(/\s+/gu, " ").trim();
  const error = send.error as ApiError | null;
  const message = `Dear Delegates\n\nGreetings from Global Connect Travels.\n\n${normalizedContent || "[Your update message]"}\n\nRegards,\nTeam Global Connect Travels`;
  function submit() {
    if (submittedRequest) { send.mutate(submittedRequest); return; }
    if (!preview.data || preview.isFetching || !normalizedContent || !chosen.length) return;
    const request: GroupUpdateRequest = {
      request_id: crypto.randomUUID(), preview_token: preview.data.preview_token, audience,
      audience_keys: chosen.map(row => row.audience_key), message_content: normalizedContent,
    };
    setSubmittedRequest(request);
    send.mutate(request);
  }
  return <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/55 p-2 sm:p-5">
    <div ref={dialogRef} onKeyDown={handleKeyDown} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} className="flex max-h-[94dvh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl bg-slate-50 shadow-2xl">
      <div className="flex items-start justify-between gap-4 border-b border-slate-200 bg-white px-5 py-5 sm:px-7">
        <div><p className="text-xs font-semibold uppercase tracking-widest text-slate-500">WhatsApp broadcast</p><h2 id={titleId} className="mt-1 text-xl font-semibold text-slate-900">Send update — {groupName}</h2><p className="mt-2 text-sm text-slate-600">Choose who should receive this update, write your message and review the phone numbers before sending.</p></div>
        <button type="button" aria-label="Close update preview" disabled={send.isPending} onClick={onClose} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"><X className="h-5 w-5" /></button>
      </div>
      <div className="space-y-5 overflow-y-auto px-4 py-5 sm:px-7">
        <GroupUpdateAudienceFields audience={audience} disabled={locked} onChange={value => { setAudience(value); setSelected(null); send.reset(); }} />
        {preview.error ? <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{(preview.error as unknown as ApiError).message || "Could not load the update audience."}</p> : null}
        {preview.data?.configuration_error ? <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">{preview.data.configuration_error}</p> : null}
        <div className="grid items-start gap-5 lg:grid-cols-2">
          <MessageComposerSection title="Write your update" description="This is a text message using your approved update template.">
            <label htmlFor={textId} className="text-sm font-semibold">Your update message</label>
            <textarea id={textId} value={content} onChange={event => setContent(event.target.value)} maxLength={600} rows={7} disabled={locked} data-dialog-initial-focus className="w-full rounded-lg border border-slate-300 bg-white p-3 text-sm leading-6" placeholder="Write the update you want these people to receive." />
            <p className="text-right text-xs text-slate-500">{content.length}/600</p>
            <p className="text-xs leading-5 text-slate-500">Line breaks and extra spaces inside your text become single spaces. The preview shows exactly how the message is formatted.</p>
          </MessageComposerSection>
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
            <div className="flex items-center gap-3 border-b p-4"><MessageCircle className="h-5 w-5 text-emerald-700" /><div><p className="text-sm font-semibold">Global Connect Travels</p><p className="text-xs text-slate-500">Message preview · {numbers} WhatsApp numbers</p></div></div>
            <div className="bg-[#f0f2ef] p-4"><div className="ml-auto max-w-[420px] rounded-xl rounded-tr-sm bg-[#dcf8c6] p-4 shadow-sm"><p data-testid="group-update-message-preview" className="whitespace-pre-wrap text-sm leading-6 [overflow-wrap:anywhere]">{parseWhatsAppBoldSegments(message).map((segment, index) => segment.bold ? <strong key={index}>{segment.text}</strong> : <span key={index}>{segment.text}</span>)}</p></div><p className="mt-4 text-center text-xs text-slate-500">Sent individually. No PDF is attached.</p></div>
          </div>
        </div>
        <MessageComposerSection title="Review recipients" description="A shared WhatsApp number receives this update once. Contacts with ambiguous matches or an earlier update still in progress are excluded.">
          <div className="flex flex-wrap items-center justify-between gap-3"><p aria-live="polite" className="text-sm font-semibold">{preview.isFetching ? "Updating audience…" : `${chosen.length} people · ${numbers} WhatsApp messages`}</p><Button variant="secondary" disabled={locked || preview.isFetching || !eligible.length} onClick={() => setSelected(chosen.length === eligible.length ? [] : null)}>{chosen.length === eligible.length && eligible.length ? "Clear selection" : "Select all eligible"}</Button></div>
          <input aria-label="Search update recipients" value={search} onChange={event => setSearch(event.target.value)} className="w-full rounded-lg border border-slate-300 p-3 text-sm" placeholder="Search name or WhatsApp number" />
          <div className="max-h-80 overflow-auto rounded-lg border border-slate-200">
            {visible.map(row => <GroupUpdateRecipientRow key={row.audience_key} row={row} selected={chosenKeys.has(row.audience_key)} disabled={locked || preview.isFetching} showDocuments={audience.document_status !== "all"} onChange={checked => { setSelected(checked ? [...chosenKeys, row.audience_key] : [...chosenKeys].filter(key => key !== row.audience_key)); }} />)}
            {!preview.isFetching && !visible.length ? <p className="p-4 text-sm text-slate-600">No matching people. Check the filters and this group’s linked WhatsApp broadcasts.</p> : null}
          </div>
        </MessageComposerSection>
        {error ? <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error.message || "Could not confirm the send request."}{submittedRequest ? " Retry to check the same request; this will not create another send." : ""}</p> : null}
        {send.data ? <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">{send.data.message}</p> : null}
      </div>
      <div className="flex flex-wrap justify-end gap-3 border-t border-slate-200 bg-white px-5 py-4">
        <Button variant="secondary" disabled={locked || preview.isFetching} onClick={() => { setSelected(null); send.reset(); void preview.refetch(); }}><RefreshCw className="h-4 w-4" />Refresh preview</Button>
        <Button variant="secondary" disabled={send.isPending} onClick={onClose}>{send.isSuccess ? "Done" : "Cancel"}</Button>
        <Button onClick={submit} isLoading={send.isPending} disabled={send.isSuccess || (!submittedRequest && (!preview.data?.can_send || preview.isFetching || preview.isError || !normalizedContent || !chosen.length))}><Send className="h-4 w-4" />{submittedRequest && send.isError ? "Retry same request" : `Send update to ${numbers}`}</Button>
      </div>
    </div>
  </div>;
}

"use client";

import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Info, RefreshCw, Send } from "lucide-react";
import { Button } from "@/components/ui";
import type { ApiError } from "@/lib/api/client";
import { distributionDocumentLabel } from "@/features/documents/config/document-distribution-lanes";
import { groupUpdatesApi, type GroupUpdateAudience, type GroupUpdateRequest } from "../api/group-updates.api";
import { useGroupUpdateAudience } from "../hooks/use-group-update-audience";
import { updateAudienceSummary } from "../utils/group-update-audience";
import { GroupUpdateAudienceFields } from "./group-update-audience";
import { GroupUpdateRecipientPicker } from "./group-update-recipient-picker";
import { MessageComposerSection, MessageDeliveryPreview } from "./whatsapp-message-composer-ui";
import { DialogFrame, ErrorBanner } from "./whatsapp-dialog-ui";
import { useWhatsAppActivityTracker } from "./whatsapp-activity-tracker";

export function GroupUpdateDialog({ groupId, groupName, broadcastGroupId, onClose }: {
  groupId: string; groupName: string; broadcastGroupId?: string; onClose: () => void;
}) {
  const textId = useId();
  const recipientId = useId();
  const queryClient = useQueryClient();
  const { registerActivity } = useWhatsAppActivityTracker();
  const [audience, setAudience] = useState<GroupUpdateAudience>({ submission_status: "all", document_status: "all", document_type: "visa" });
  const allAudience = useGroupUpdateAudience(groupId, audience.document_type);
  const preview = useQuery({
    queryKey: ["group-update-preview", groupId, audience],
    queryFn: ({ signal }) => groupUpdatesApi.preview(groupId, audience, signal), staleTime: 0,
    refetchInterval: query => query.state.data?.recipients.some(row => ["queued", "processing"].includes(row.latest_update_status ?? "")) ? 5000 : false,
  });
  const [selected, setSelected] = useState<string[] | null>(null);
  const [previewKey, setPreviewKey] = useState("");
  const [content, setContent] = useState("");
  // Keep one exact request after a lost response, including its idempotency key.
  const [submittedRequest, setSubmittedRequest] = useState<GroupUpdateRequest | null>(null);
  const send = useMutation({
    mutationFn: (request: GroupUpdateRequest) => groupUpdatesApi.send(groupId, request),
    onSuccess: result => {
      for (const batch of result.batches ?? []) registerActivity({
        id: batch.batch_id, kind: "broadcast", messageType: "document_update", startedAt: Date.now(),
        title: "Update message broadcast", contextLabel: groupName, sourceGroupId: batch.broadcast_group_id,
        documentType: null, total: batch.queued_count, queued: batch.queued_count, sent: 0, failed: 0, deliveryUnknown: 0,
      });
      void queryClient.invalidateQueries({ queryKey: ["group-update-preview", groupId] });
    },
    onError: (error: ApiError) => { if ([400, 403, 404, 409, 422].includes(error.status ?? 0)) setSubmittedRequest(null); },
  });
  const rows = (preview.data?.recipients ?? []).filter(row => !broadcastGroupId || row.broadcast_group_id === broadcastGroupId);
  const allRows = (allAudience.data?.recipients ?? []).filter(row => !broadcastGroupId || row.broadcast_group_id === broadcastGroupId);
  const eligible = rows.filter(row => row.eligible);
  const selectedKeys = selected === null ? null : new Set(selected);
  const chosen = eligible.filter(row => selectedKeys === null ? row.latest_update_status === null : selectedKeys.has(row.audience_key));
  const chosenKeys = new Set(chosen.map(row => row.audience_key));
  const numbers = new Set(chosen.map(row => row.phone_number)).size;
  const previewPerson = rows.find(row => row.audience_key === previewKey) ?? chosen[0] ?? rows[0];
  const locked = send.isPending || send.isSuccess || submittedRequest !== null;
  const normalizedContent = content.replace(/\s+/gu, " ").trim();
  const error = send.error as ApiError | null;
  const documentLabel = distributionDocumentLabel(audience.document_type);
  const message = `Dear Delegates\n\nGreetings from Global Connect Travels.\n\n${normalizedContent || "[Your update message]"}\n\nRegards,\nTeam Global Connect Travels`;
  function submit() {
    if (submittedRequest) { send.mutate(submittedRequest); return; }
    if (!preview.data || preview.isFetching || !normalizedContent || !chosen.length) return;
    const request: GroupUpdateRequest = { request_id: crypto.randomUUID(), preview_token: preview.data.preview_token, audience, audience_keys: chosen.map(row => row.audience_key), message_content: normalizedContent };
    setSubmittedRequest(request); send.mutate(request);
  }
  return <DialogFrame title="Preview Update Message" description={groupName} eyebrow="WhatsApp communications" layout="composer" widthClass="max-w-6xl" isBusy={send.isPending} onClose={onClose}>
    <form className="flex min-h-0 flex-1 flex-col" onSubmit={event => { event.preventDefault(); submit(); }}>
      <div className="min-h-0 space-y-5 overflow-y-auto overscroll-contain bg-slate-50/70 px-4 py-5 sm:px-7 sm:py-6">
        <GroupUpdateAudienceFields audience={audience} rows={allRows} loading={allAudience.isFetching && !allAudience.data} disabled={locked} onChange={value => { setAudience(value); setSelected(null); setPreviewKey(""); send.reset(); }} />
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-blue-100 bg-blue-50/70 px-4 py-3 text-xs text-slate-600"><p><strong className="text-slate-800">Audience: </strong>{updateAudienceSummary(audience, documentLabel)}</p><p>{rows.length.toLocaleString()} matching travellers · <strong className="text-slate-800">{numbers} numbers selected</strong></p></div>
        {preview.error || allAudience.error ? <ErrorBanner message={(preview.error as unknown as ApiError)?.message || "Could not load the update audience. Refresh the preview."} /> : null}
        {preview.data?.configuration_error && <ErrorBanner message={preview.data.configuration_error} />}
        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
          <div className="min-w-0 space-y-5">
            <GroupUpdateRecipientPicker key={`${audience.submission_status}:${audience.document_status}:${audience.document_type}`} rows={rows} selectedKeys={chosenKeys} disabled={locked} loading={preview.isFetching} documentLabel={documentLabel} onChange={setSelected} />
            <MessageComposerSection title="Message content" description="Write the update your selected recipients will receive.">
              <div className="flex gap-2.5 rounded-lg bg-blue-50/70 px-3 py-3 text-xs leading-5 text-slate-600"><Info className="mt-0.5 h-4 w-4 shrink-0" /><p>Edit the update paragraph below. The greeting and sign-off are fixed in your approved template. This message has no attachment.</p></div>
              <div><label htmlFor={textId} className="block text-sm font-medium text-slate-700">Your update message <span className="text-red-600">*</span></label><div className="mt-1.5 overflow-hidden rounded-lg border border-slate-300 bg-white focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-100"><div className="border-b border-slate-200 bg-slate-50 px-3 py-2 text-right text-[11px] tabular-nums text-slate-400">{content.length} / 600</div><textarea aria-label="Your update message" id={textId} value={content} onChange={event => setContent(event.target.value)} maxLength={600} rows={7} disabled={locked} className="block w-full resize-y border-0 bg-white p-3 text-sm leading-6 outline-none" placeholder="Write the update you want these people to receive." required /></div><p className="mt-2 text-xs leading-5 text-slate-500">Line breaks and extra spaces become single spaces in the update paragraph. The preview shows the final formatting.</p></div>
            </MessageComposerSection>
          </div>
          <aside className="min-w-0 space-y-3 lg:sticky lg:top-0"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold text-slate-900">Individual WhatsApp preview</h3><p className="text-xs text-slate-500">{chosen.length} selected of {rows.length} matching</p></div>
            <MessageDeliveryPreview messageType="document_update" preview={{ recipient_name: previewPerson?.name ?? "your recipient", rendered_message: message, template_name: preview.data?.template_name ?? "pending_v1" }} previewIsCurrent={!preview.isFetching && !preview.isError && Boolean(preview.data)} previewFailed={preview.isError} headerImagePreview={null} headerImageId={null}>
              <label htmlFor={recipientId} className="mb-1.5 block text-xs font-medium text-slate-700">Preview recipient</label><select id={recipientId} value={previewPerson?.audience_key ?? ""} onChange={event => setPreviewKey(event.target.value)} className="h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm" disabled={!rows.length}>{rows.map(row => <option key={row.audience_key} value={row.audience_key}>{row.name} · {row.phone_number ?? "No valid number"}</option>)}</select>{previewPerson && <p className="mt-2 break-words text-xs text-slate-500">{previewPerson.phone_number} · {previewPerson.phone_source === "submitted" ? "Submitted WhatsApp number" : "Imported broadcast number"}{chosenKeys.has(previewPerson.audience_key) ? " · Selected for this send" : " · Not selected"}</p>}
            </MessageDeliveryPreview>
          </aside>
        </div>
        {error && <ErrorBanner message={`${error.message || "Could not confirm the send request."}${submittedRequest ? " Retry the same request to check its result without creating another send." : ""}`} />}
        {send.data && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{send.data.message}</p>}
      </div>
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-white px-4 py-4 sm:px-7"><p className="flex items-center gap-2 text-xs text-slate-500"><Info className="h-4 w-4 shrink-0" />Review the selected people, numbers and message before sending.</p><div className="flex flex-wrap gap-2"><Button type="button" variant="secondary" disabled={locked || preview.isFetching} onClick={() => { setSelected(null); send.reset(); void preview.refetch(); void allAudience.refetch(); }}><RefreshCw className="h-4 w-4" />Refresh preview</Button><Button type="button" variant="secondary" disabled={send.isPending} onClick={onClose}>{send.isSuccess ? "Done" : "Cancel"}</Button><Button type="submit" isLoading={send.isPending} disabled={send.isSuccess || (!submittedRequest && (!preview.data?.can_send || preview.isFetching || preview.isError || allAudience.isError || !normalizedContent || !chosen.length))}><Send className="h-4 w-4" />{submittedRequest && send.isError ? "Retry same request" : `Send individually to ${numbers}`}</Button></div></div>
    </form>
  </DialogFrame>;
}

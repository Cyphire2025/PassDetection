"use client";

import { useEffect, useId, useMemo, useRef, useState, type FormEvent } from "react";
import { Send } from "lucide-react";
import { Button, Input } from "@/components/ui";
import type { WhatsAppBulkResendPreviewResponse, WhatsAppPreviewResponse } from "../api/whatsapp.api";
import { usePreviewWhatsAppBulkResendMessage, usePreviewWhatsAppMessage, useWhatsAppGroup } from "../hooks/use-whatsapp";
import { canRetryOrResendRecipient, isRecipientEligible, welcomeDeliveryBlockReason } from "../utils/recipient-delivery";
import { GROUP_INVITE_LINK_HELP, validWhatsAppGroupInviteLink } from "../utils/group-invite";
import { DialogFrame, ErrorBanner, readErrorMessage } from "./whatsapp-dialog-ui";
import { MessageComposerSection, MessageDeliveryPreview } from "./whatsapp-message-composer-ui";
import { RecipientBulkComposerAudience } from "./whatsapp-bulk-composer-audience";
import { GroupInvitePhotoPicker, useGroupInviteImage } from "./whatsapp-group-invite-image";
import type { MessagePreviewDialogProps, MessagePreviewSendPayload } from "./whatsapp-message-preview-dialog";

export function GroupInvitePreviewDialog({ group, targetRecipient, bulkRecipients, hiddenSelectedCount = 0, isSending, onClose, onSend }: MessagePreviewDialogProps) {
  const { data: detail, isLoading: isLoadingDetail } = useWhatsAppGroup(group.id);
  const { mutate: requestPreview } = usePreviewWhatsAppMessage();
  const { mutate: requestBulkPreview } = usePreviewWhatsAppBulkResendMessage();
  const [messageContent, setMessageContent] = useState<string | null>(null);
  const [groupInviteLink, setGroupInviteLink] = useState<string | null>(null);
  const [selectionMode, setSelectionMode] = useState<"all" | "custom">("all");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [previewRecipientId, setPreviewRecipientId] = useState<string | null>(null);
  const [preview, setPreview] = useState<WhatsAppPreviewResponse | null>(null);
  const image = useGroupInviteImage(preview?.header_image_id ?? null);
  const [bulkPreview, setBulkPreview] = useState<WhatsAppBulkResendPreviewResponse | null>(null);
  const [checkedKey, setCheckedKey] = useState<string | null>(null);
  const [retryNonce, setRetryNonce] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [recovery, setRecovery] = useState<{ key: string; payload: MessagePreviewSendPayload } | null>(null);
  const requestSequence = useRef(0);
  const sendingRef = useRef(false);
  const contentId = useId();
  const linkId = useId();
  const searchId = useId();
  const bulkMode = bulkRecipients !== undefined;
  const bulkIds = useMemo(() => bulkRecipients?.map((recipient) => recipient.id) ?? null, [bulkRecipients]);
  const archived = Boolean(group.is_archived || detail?.is_archived);
  const pending = submitting || isSending;
  const resolvedContent = (messageContent ?? preview?.message_content ?? "").trim();
  const resolvedLink = (groupInviteLink ?? preview?.group_invite_link ?? "").trim();
  const validLink = validWhatsAppGroupInviteLink(resolvedLink);
  const eligibleRecipients = useMemo(() => detail?.recipients.filter((recipient) => isRecipientEligible(recipient, "group_invite")) ?? [], [detail?.recipients]);
  const currentRecipients = useMemo(() => new Map(detail?.recipients.map((recipient) => [recipient.id, recipient])), [detail?.recipients]);
  const selectableIds = bulkIds ?? eligibleRecipients.filter((recipient) => selectionMode === "all" || selectedIds.includes(recipient.id)).map((recipient) => recipient.id);
  const effectivePreviewRecipientId = previewRecipientId && selectableIds.includes(previewRecipientId) ? previewRecipientId : null;
  const target = targetRecipient ? currentRecipients.get(targetRecipient.recipientId) : null;
  const targetAllowed = !targetRecipient || Boolean(target && canRetryOrResendRecipient(target, "group_invite", targetRecipient.action));
  const draftKey = JSON.stringify({ messageContent, groupInviteLink, selectionMode, selectedIds, bulkIds, imageRevision: image.revision });
  const requestKey = JSON.stringify({ groupId: group.id, draftKey, previewRecipientId: effectivePreviewRecipientId, targetId: targetRecipient?.recipientId, recipients: detail?.recipients, optIn: detail?.recipient_opt_in_confirmed });
  const previewCurrent = Boolean(preview && checkedKey === requestKey);

  useEffect(() => {
    const sequence = ++requestSequence.current;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      const onError = (cause: unknown) => {
        if (controller.signal.aborted || requestSequence.current !== sequence) return;
        setCheckedKey(null);
        setError(readErrorMessage(cause, "Could not generate the group invite preview."));
      };
      const onSuccess = (response: WhatsAppPreviewResponse) => {
        if (controller.signal.aborted || requestSequence.current !== sequence) return;
        setPreview(response);
        setCheckedKey(requestKey);
        setError(null);
      };
      if (bulkIds) {
        requestBulkPreview({ groupId: group.id, messageType: "group_invite", recipientIds: bulkIds, previewRecipientId: effectivePreviewRecipientId, overrides: { messageContent, groupInviteLink, headerImageId: null }, signal: controller.signal }, {
          onSuccess: (response) => {
            if (controller.signal.aborted || requestSequence.current !== sequence) return;
            setBulkPreview(response);
            onSuccess(response);
          }, onError,
        });
      } else {
        requestPreview({ groupId: group.id, draft: {
          message_type: "group_invite", message_content: messageContent, group_invite_link: groupInviteLink, header_image_id: null,
          recipient_id: targetRecipient ? null : effectivePreviewRecipientId,
          resend_recipient_id: targetRecipient?.recipientId ?? null,
          recipient_ids: !targetRecipient && selectionMode === "custom" ? selectedIds : null,
        }, signal: controller.signal }, { onSuccess, onError });
      }
    }, 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [group.id, messageContent, groupInviteLink, selectionMode, selectedIds, bulkIds, effectivePreviewRecipientId, targetRecipient, requestKey, retryNonce, requestPreview, requestBulkPreview]);

  const bulkEligibleIds = bulkPreview?.eligible_recipient_ids.filter((id) => {
    const recipient = currentRecipients.get(id) ?? bulkRecipients?.find((item) => item.id === id);
    return recipient && !welcomeDeliveryBlockReason(recipient, "group_invite");
  }) ?? [];
  const eligibleCount = bulkMode ? bulkEligibleIds.length : targetRecipient ? (targetAllowed ? 1 : 0)
    : previewCurrent ? preview?.eligible_recipient_count ?? 0 : 0;
  const welcomeReason = (preview?.welcome_required_count ?? 0) > 0
    ? preview?.welcome_required_reason || "Welcome must be delivered to the selected numbers before sending other messages."
    : target ? welcomeDeliveryBlockReason(target, "group_invite") : null;
  const missingPhotoCount = bulkMode && previewCurrent ? bulkPreview?.missing_header_image_count ?? 0 : 0;
  const needsReplacementPhoto = missingPhotoCount > 0 && !image.file;
  const canSend = Boolean(previewCurrent && image.hasImage && !image.error && !needsReplacementPhoto && !archived && detail?.recipient_opt_in_confirmed && resolvedContent && validLink && eligibleCount > 0 && targetAllowed && !welcomeReason
    && (bulkMode || targetRecipient || selectionMode !== "custom" || selectedIds.length > 0));
  const recoverable = Boolean(bulkMode && recovery?.key === draftKey && !archived);
  const submitPayload = async (payload: MessagePreviewSendPayload) => {
    if (archived || pending || sendingRef.current) return;
    sendingRef.current = true;
    setSubmitting(true);
    setError(null);
    try {
      await onSend(payload);
      setRecovery(null);
    } catch (cause) {
      if (bulkMode) setRecovery({ key: draftKey, payload });
      setError(readErrorMessage(cause, "The group invite could not be submitted."));
    } finally {
      sendingRef.current = false;
      setSubmitting(false);
    }
  };
  const handleSend = async (event: FormEvent) => {
    event.preventDefault();
    if (!canSend || pending || sendingRef.current) return;
    await submitPayload({ passportIntro: "", passportLink: "", messageContent: resolvedContent, groupInviteLink: resolvedLink,
      headerImage: image.file, headerImageId: bulkMode ? null : image.imageId, supportContactIds: null,
      recipientIds: bulkIds ?? (selectionMode === "custom" ? selectedIds : null),
      ...(bulkMode ? { bulkDraft: { messageContent: messageContent === null ? null : resolvedContent, groupInviteLink: groupInviteLink === null ? null : resolvedLink, headerImageId: null } } : {}),
    });
  };
  const filteredRecipients = eligibleRecipients.filter((recipient) => `${recipient.name} ${recipient.normalized_phone_number}`.toLowerCase().includes(search.trim().toLowerCase()));
  const recipientOptions = bulkMode ? (bulkRecipients ?? []).filter((recipient) => bulkEligibleIds.includes(recipient.id))
    : selectionMode === "custom" ? eligibleRecipients.filter((recipient) => selectedIds.includes(recipient.id)) : eligibleRecipients;

  return <DialogFrame title={`${bulkMode ? "Resend" : targetRecipient ? targetRecipient.action === "retry" ? "Retry" : "Resend" : "Send"} Group Invite`} onClose={onClose} isBusy={pending} widthClass="max-w-6xl" layout="composer" eyebrow="WhatsApp communications" description={group.name}>
    <form className="flex min-h-0 flex-1 flex-col" onSubmit={handleSend}>
      <div className="min-h-0 overflow-y-auto overscroll-contain bg-slate-50/70 px-4 py-5 sm:px-7 sm:py-6">
        <fieldset disabled={archived || pending} className="contents">
          {archived && <ErrorBanner message="This broadcast is archived. Restore it before editing or sending messages." />}
          <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
            <div className="min-w-0 space-y-5">
              <GroupInvitePhotoPicker image={image} savedImageId={preview?.header_image_id ?? null} bulkMode={bulkMode} />
              <MessageComposerSection title="Group invitation" description="Edit the invitation and group link. The greeting and sign-off stay exactly as shown in the preview.">
                <div className="space-y-2">
                  <label htmlFor={contentId} className="text-sm font-semibold text-slate-800">Invitation message</label>
                  <textarea id={contentId} rows={6} maxLength={600} required value={messageContent ?? preview?.message_content ?? ""} onChange={(event) => setMessageContent(event.target.value)} className="block w-full rounded-xl border border-slate-300 bg-white p-3 text-sm leading-6 text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                  <p className="text-xs text-slate-500">{(messageContent ?? preview?.message_content ?? "").length} / 600 characters</p>
                  {bulkMode && messageContent !== null && <button type="button" className="text-xs font-semibold text-blue-700 underline" onClick={() => setMessageContent(null)}>Keep each recipient’s saved invitation</button>}
                </div>
                <div className="space-y-2">
                  <label htmlFor={linkId} className="text-sm font-semibold text-slate-800">WhatsApp group invite link</label>
                  <Input id={linkId} type="url" required value={groupInviteLink ?? preview?.group_invite_link ?? ""} onChange={(event) => setGroupInviteLink(event.target.value)} placeholder="https://chat.whatsapp.com/YourInviteCode" aria-invalid={Boolean(resolvedLink && !validLink)} aria-describedby={`${linkId}-hint`} maxLength={2048} />
                  <p id={`${linkId}-hint`} className={`text-xs leading-5 ${resolvedLink && !validLink ? "text-red-700" : "text-slate-500"}`}>{GROUP_INVITE_LINK_HELP}</p>
                  {bulkMode && groupInviteLink !== null && <button type="button" className="text-xs font-semibold text-blue-700 underline" onClick={() => setGroupInviteLink(null)}>Keep each recipient’s saved group link</button>}
                </div>
                {bulkMode && <p className="rounded-lg bg-blue-50 p-3 text-xs leading-5 text-blue-800">Unchanged fields keep each recipient’s saved photo, invitation, and group link. A replacement photo or other edits apply to every selected recipient.</p>}
              </MessageComposerSection>
              <MessageComposerSection title="Recipients" description="Each person receives the invitation as a private WhatsApp message.">
                {bulkRecipients ? <RecipientBulkComposerAudience recipients={bulkRecipients} messageType="group_invite" hiddenCount={hiddenSelectedCount} preview={previewCurrent ? bulkPreview : null} /> : targetRecipient ? <p className="text-sm text-slate-700">{targetRecipient.recipientName} · {targetRecipient.phoneNumber}</p> : <>
                  <div className="flex flex-wrap gap-4 text-sm text-slate-700">
                    <label className="flex items-center gap-2"><input type="radio" name={`invite-audience-${contentId}`} checked={selectionMode === "all"} onChange={() => setSelectionMode("all")} />All eligible recipients</label>
                    <label className="flex items-center gap-2"><input type="radio" name={`invite-audience-${contentId}`} checked={selectionMode === "custom"} onChange={() => setSelectionMode("custom")} />Choose recipients</label>
                  </div>
                  {selectionMode === "custom" && <div className="space-y-3">
                    <label htmlFor={searchId} className="text-xs font-semibold text-slate-600">Search recipients</label>
                    <Input id={searchId} value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Name or phone number" />
                    <p className="text-xs text-slate-500">{selectedIds.length} selected. Selected recipients remain included when you search.</p>
                    <div className="max-h-64 divide-y divide-slate-100 overflow-y-auto rounded-xl border border-slate-200">
                      {filteredRecipients.map((recipient) => <label key={recipient.id} className="flex cursor-pointer items-start gap-3 p-3 text-sm">
                        <input type="checkbox" checked={selectedIds.includes(recipient.id)} onChange={(event) => { const checked = event.target.checked; setSelectedIds((current) => checked ? [...current, recipient.id] : current.filter((id) => id !== recipient.id)); }} className="mt-1 h-4 w-4" />
                        <span><span className="block font-medium text-slate-800">{recipient.name || "Guest"}</span><span className="text-xs text-slate-500">{recipient.normalized_phone_number}</span></span>
                      </label>)}
                      {!filteredRecipients.length && <p className="p-3 text-sm text-slate-500">No eligible recipients match this search.</p>}
                    </div>
                  </div>}
                  <p className="text-xs leading-5 text-slate-500">Previous successful invites, sends in progress, and unknown delivery outcomes are skipped. Welcome delivery must be confirmed first.</p>
                </>}
              </MessageComposerSection>
            </div>
            <aside className="min-w-0 space-y-3 lg:sticky lg:top-0">
              <MessageDeliveryPreview preview={preview} previewIsCurrent={previewCurrent} previewFailed={Boolean(error)} messageType="group_invite" headerImagePreview={image.previewUrl} headerImageId={image.imageId}>
                {!targetRecipient && recipientOptions.length > 1 && <label className="block text-xs font-medium text-slate-700">Preview recipient<select className="mt-2 h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm" value={effectivePreviewRecipientId ?? preview?.recipient_id ?? ""} onChange={(event) => setPreviewRecipientId(event.target.value)}>{recipientOptions.map((recipient) => <option key={recipient.id} value={recipient.id}>{recipient.name || "Guest"} · {recipient.normalized_phone_number}</option>)}</select></label>}
              </MessageDeliveryPreview>
              {previewCurrent && <p className="text-xs leading-5 text-slate-500">{eligibleCount} ready · {preview?.already_sent_count ?? 0} already sent · {preview?.in_progress_count ?? 0} in progress · {preview?.uncertain_recipient_count ?? 0} need review</p>}
            </aside>
          </div>
          <div className="mt-5 space-y-3">
            {isLoadingDetail && <p role="status" className="text-sm text-slate-500">Loading recipient details...</p>}
            {detail && !detail.recipient_opt_in_confirmed && <ErrorBanner message="This older list has no recorded recipient opt-in confirmation. Create a new list before sending." />}
            {!targetAllowed && <ErrorBanner message="This recipient’s delivery state changed. Refresh the recipient list before trying again." />}
            {welcomeReason && <ErrorBanner message={welcomeReason} />}
            {needsReplacementPhoto && <ErrorBanner message={`${missingPhotoCount} selected recipient${missingPhotoCount === 1 ? " has" : "s have"} no saved invitation photo. Choose a replacement photo before resending.`} />}
            {!previewCurrent && !error && <p role="status" className="text-sm text-slate-500">Updating message preview. Sending will be available after this version has been checked.</p>}
            {error && <ErrorBanner message={error} />}
            {error && !previewCurrent && <Button type="button" variant="secondary" onClick={() => { setError(null); setRetryNonce((value) => value + 1); }}>Retry preview</Button>}
            {recoverable && <p role="status" className="text-sm text-amber-800">The last resend has not been confirmed. Check the same request safely without sending it twice.</p>}
          </div>
        </fieldset>
      </div>
      <div data-testid="whatsapp-composer-footer" className="flex shrink-0 flex-col gap-3 border-t border-slate-200 bg-white px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-7">
        <p role="status" className="text-xs text-slate-500">{pending ? "Uploading your photo and submitting group invites..." : canSend ? "Message checked and ready to send." : "Choose a photo, complete the invitation and official group link, then review the preview."}</p>
        <div className="flex min-w-0 justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose} disabled={pending}>Cancel</Button>
          <Button type={recoverable ? "button" : "submit"} onClick={recoverable && recovery ? () => void submitPayload(recovery.payload) : undefined} disabled={!recoverable && !canSend} isLoading={pending} className="min-w-0"><Send className="h-4 w-4 shrink-0" /><span className="truncate">{recoverable ? "Check resend status" : bulkMode ? `Resend to ${eligibleCount} selected` : targetRecipient ? `${targetRecipient.action === "retry" ? "Retry" : "Resend"} to ${targetRecipient.recipientName}` : `Send individually to ${eligibleCount}`}</span></Button>
        </div>
      </div>
    </form>
  </DialogFrame>;
}

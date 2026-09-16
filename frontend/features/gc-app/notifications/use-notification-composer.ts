"use client";

import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { notificationsApi } from "./notifications.api";
import { isDeletedWithoutSend, isNotFound, isRejectedBeforeSend, notificationError } from "./notification-errors";
import { clearPendingSend, pendingSendKey, persistPendingSend, readPendingSend } from "./pending-send";
import { NOTIFICATION_BODY_LIMIT, NOTIFICATION_TITLE_LIMIT, type NotificationBatch, type NotificationDraft, type NotificationDraftInput, type NotificationPreview, type NotificationSendInput } from "./notification-types";

const emptyMessage = (): NotificationDraftInput => ({ title: "", body: "", audience: "selected_groups", group_ids: [] });
const inputFrom = (value: NotificationDraftInput): NotificationDraftInput => ({ title: value.title, body: value.body, audience: value.audience, group_ids: value.audience === "all_active_trips" ? [] : [...value.group_ids] });
const sameInput = (a: NotificationDraftInput, b: NotificationDraftInput) => a.title === b.title && a.body === b.body && a.audience === b.audience && [...a.group_ids].sort().join() === [...b.group_ids].sort().join();

export function useNotificationComposer(agencyId: string, actorId: string) {
  const queryClient = useQueryClient();
  const storageKey = pendingSendKey(agencyId, actorId);
  const [form, setForm] = useState<NotificationDraftInput>(emptyMessage);
  const [draft, setDraft] = useState<NotificationDraft | null>(null);
  const [groupNames, setGroupNames] = useState<Record<string, string>>({});
  const [review, setReview] = useState<{ draft: NotificationDraft; preview: NotificationPreview } | null>(null);
  const [pending, setPending] = useState(() => readPendingSend(storageKey));
  const [sendInput, setSendInput] = useState<NotificationSendInput | null>(null);
  const [lastBatch, setLastBatch] = useState<NotificationBatch | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [resending, setResending] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const running = useRef(false);
  const hasEdits = draft ? !sameInput(form, draft) : Boolean(form.title || form.body || form.group_ids.length || form.audience === "all_active_trips");

  const refreshLists = () => { void queryClient.invalidateQueries({ queryKey: ["gc-app", agencyId, "notifications"] }).catch(() => undefined); };
  const run = async (operation: () => Promise<void>, fallback: string) => {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    try { await operation(); }
    catch (cause) { setError(notificationError(cause, fallback)); }
    finally { running.current = false; setBusy(false); }
  };
  const applyNames = (value: { group_ids: string[]; group_names?: string[] }) => setGroupNames(Object.fromEntries(value.group_ids.map((id, index) => [id, value.group_names?.[index] ?? `Selected trip ${index + 1}`])));
  const accept = (batch: NotificationBatch) => {
    try { clearPendingSend(storageKey); } catch { /* A retained ID safely resolves to this same batch after reload. */ }
    setPending(null);
    setSendInput(null);
    setReview(null);
    setLastBatch(batch);
    setDraft(null);
    setForm(emptyMessage());
    setGroupNames({});
    setResending(false);
    setEditorOpen(false);
    setNotice("Send recorded. Check the delivery summary below; phone display is not confirmed.");
    refreshLists();
  };
  const releaseRejectedSend = (cause: unknown): boolean => {
    if (!isRejectedBeforeSend(cause)) return false;
    clearPendingSend(storageKey);
    setPending(null);
    setSendInput(null);
    setNotice("The server rejected this request before recording a send. Your message is kept; update it or its audience and review again.");
    setEditorOpen(true);
    return true;
  };
  const saveCurrent = async (): Promise<NotificationDraft> => {
    const input = { ...form, title: form.title.trim(), body: form.body.trim(), group_ids: [...form.group_ids].sort() };
    if (!input.title || !input.body) throw new Error("Enter a notification title and message.");
    if (input.title.length > NOTIFICATION_TITLE_LIMIT || input.body.length > NOTIFICATION_BODY_LIMIT) throw new Error("Shorten the notification to the displayed character limits.");
    if (input.audience === "selected_groups" && input.group_ids.length === 0) throw new Error("Choose at least one active trip.");
    const saved = draft && sameInput(input, draft) ? draft : draft
      ? await notificationsApi.updateDraft(agencyId, draft, input)
      : await notificationsApi.createDraft(agencyId, input);
    setDraft(saved);
    setForm(inputFrom(saved));
    applyNames(saved);
    refreshLists();
    return saved;
  };

  const change = (next: NotificationDraftInput) => {
    if (busy || pending) return;
    setForm(next);
    setReview(null);
    setNotice(null);
  };
  const save = () => run(async () => {
    if (pending) return;
    await saveCurrent();
    setEditorOpen(false);
    setNotice("Message saved. This action did not send a phone notification.");
  }, "The notification draft could not be saved.");
  const prepareReview = () => run(async () => {
    if (pending) return;
    const saved = await saveCurrent();
    const preview = await notificationsApi.preview(agencyId, saved);
    setReview({ draft: saved, preview });
    setNotice(null);
  }, "The audience could not be reviewed. Nothing has been sent.");

  const send = () => run(async () => {
    if (!review || pending) return;
    const requestId = crypto.randomUUID();
    const marker = { request_id: requestId, draft_id: review.draft.id };
    const input = { request_id: requestId, expected_revision: review.preview.draft_revision, preview_token: review.preview.preview_token };
    try { persistPendingSend(storageKey, marker); }
    catch { throw new Error("This browser could not keep the send-recovery reference. Allow session storage before sending."); }
    setPending(marker);
    setSendInput(input);
    try { accept(await notificationsApi.send(agencyId, marker.draft_id, input)); }
    catch (cause) {
      setReview(null);
      if (releaseRejectedSend(cause)) throw cause;
      setEditorOpen(false);
      throw new Error(`${notificationError(cause, "The server response was not received.")} Check this send before creating another notification.`);
    }
  }, "The send could not be confirmed. Check its recorded outcome before starting another send.");

  const checkPending = () => run(async () => {
    if (!pending) return;
    try { accept(await notificationsApi.byRequest(agencyId, pending.request_id, pending.draft_id)); }
    catch (cause) {
      if (releaseDeletedSend(cause)) return;
      if (!isNotFound(cause)) throw cause;
      setNotice("No recorded send was found yet. You can check again or review and retry this same request. A new send has not been started.");
    }
  }, "The recorded send could not be checked. Keep this recovery reference and try again.");

  const reviewPending = () => run(async () => {
    if (!pending) return;
    try { accept(await notificationsApi.byRequest(agencyId, pending.request_id, pending.draft_id)); return; }
    catch (cause) { if (releaseDeletedSend(cause)) return; if (!isNotFound(cause)) throw cause; }
    const saved = await notificationsApi.getDraft(agencyId, pending.draft_id);
    const preview = await notificationsApi.preview(agencyId, saved);
    setDraft(saved);
    setForm(inputFrom(saved));
    applyNames(saved);
    setReview({ draft: saved, preview });
    setSendInput({ request_id: pending.request_id, expected_revision: preview.draft_revision, preview_token: preview.preview_token });
    setNotice("Review the saved message and current audience. Retrying uses the original send reference to prevent another send from being created.");
  }, "The previous send could not be reviewed. Its recovery reference is kept.");

  const retryPending = () => run(async () => {
    if (!pending || !sendInput || !review) return;
    try { accept(await notificationsApi.send(agencyId, pending.draft_id, sendInput)); }
    catch (cause) { setReview(null); releaseRejectedSend(cause); throw cause; }
  }, "This send is still unconfirmed. Check again before starting another notification.");

  const edit = (saved: NotificationDraft) => {
    if (busy || pending || hasEdits) return;
    setForm(inputFrom(saved)); setDraft(saved); applyNames(saved);
    setReview(null); setError(null); setNotice(null); setResending(false);
    setEditorOpen(true);
  };
  const resendSaved = (saved: NotificationDraft) => {
    if (busy || pending || hasEdits) return;
    edit(saved);
    setResending(true);
    setNotice("Review the current audience before sending again. Previous recipients may receive this alert again.");
  };
  const resend = (batch: NotificationBatch) => {
    if (busy || pending || hasEdits) return;
    setForm(inputFrom(batch)); setDraft(null); applyNames(batch);
    setReview(null); setError(null); setResending(true);
    setEditorOpen(true);
    setNotice("Preparing another phone alert from this previous send. Review the current audience; recipients may receive the alert again.");
  };
  const discard = () => {
    if (busy || pending) return;
    setForm(emptyMessage()); setDraft(null); setGroupNames({}); setReview(null);
    setError(null); setNotice(null); setResending(false);
    setEditorOpen(false);
  };

  const openNew = () => {
    if (busy || pending || hasEdits) return;
    discard();
    setEditorOpen(true);
  };

  const releaseDeletedSend = (cause: unknown): boolean => {
    // Only the server's locked draft + second request lookup can prove this.
    // Ordinary 404/410 responses and failed lookups remain recoverable.
    if (!isDeletedWithoutSend(cause)) return false;
    clearPendingSend(storageKey);
    setPending(null); setSendInput(null); setReview(null);
    setForm(emptyMessage()); setDraft(null); setGroupNames({});
    setEditorOpen(false); setResending(false);
    setNotice("This saved notification was deleted before this send was recorded. No send was created for this request. You can create a new notification.");
    refreshLists();
    return true;
  };

  return { form, draft, groupNames, review, pending, lastBatch, busy, error, notice, hasEdits, resending, editorOpen,
    change, save, prepareReview, send, checkPending, reviewPending, retryPending, edit, resend, resendSaved, discard, openNew,
    closeReview: () => { if (!busy) setReview(null); }, selectBatch: setLastBatch };
}

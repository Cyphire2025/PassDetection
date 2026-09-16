"use client";

import { useState } from "react";
import { Bell, Send, Smartphone } from "lucide-react";
import { Button, Input } from "@/components/ui";
import { GcDialog } from "../components/gc-dialog";
import { GcAlert } from "../components/gc-app-feedback";
import { NotificationAudiencePicker } from "./notification-audience-picker";
import { NOTIFICATION_BODY_LIMIT, NOTIFICATION_TITLE_LIMIT } from "./notification-types";
import type { useNotificationComposer } from "./use-notification-composer";

export function NotificationComposerDialog({ agencyId, composer }: {
  agencyId: string;
  composer: ReturnType<typeof useNotificationComposer>;
}) {
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const disabled = composer.busy || Boolean(composer.pending);
  const close = () => {
    if (disabled) return;
    if (composer.hasEdits) setConfirmDiscard(true);
    else composer.discard();
  };
  return <GcDialog open title={confirmDiscard ? "Discard unsaved changes?" : composer.resending ? "Resend notification" : composer.draft ? "Edit notification" : "New notification"}
    description={confirmDiscard ? "Changes since your last save will be lost. Saved messages and send history will stay." : "Write your message, choose who receives it, then review before sending."}
    size={confirmDiscard ? "md" : "xl"} closeDisabled={disabled} onClose={confirmDiscard ? () => setConfirmDiscard(false) : close}
    footer={confirmDiscard ? <>
      <Button variant="secondary" onClick={() => setConfirmDiscard(false)}>Keep editing</Button>
      <Button variant="danger" onClick={composer.discard}>Discard changes</Button>
    </> : <>
      <Button type="button" variant="ghost" disabled={disabled} onClick={close}>Cancel</Button>
      <Button type="button" variant="secondary" disabled={disabled} onClick={() => void composer.save()}>Save notification</Button>
      <Button type="button" disabled={disabled} isLoading={composer.busy} leftIcon={<Send className="h-4 w-4" aria-hidden="true" />} onClick={() => void composer.prepareReview()}>Review audience</Button>
    </>}>
    {!confirmDiscard && <div className="space-y-5">
      {composer.error && <GcAlert message={composer.error} />}
      {composer.notice && <GcAlert tone="info" message={composer.notice} />}
      <div className="grid min-w-0 gap-6 md:grid-cols-[minmax(0,1fr)_260px]">
        <fieldset disabled={disabled} className="min-w-0 space-y-4">
          <Input label="Notification title" required maxLength={NOTIFICATION_TITLE_LIMIT} value={composer.form.title} placeholder="A short, clear headline" hint={`${composer.form.title.length}/${NOTIFICATION_TITLE_LIMIT} characters`} onChange={(event) => composer.change({ ...composer.form, title: event.target.value })} />
          <div className="flex flex-col gap-1.5 text-sm text-slate-700">
            <label htmlFor="gc-notification-message" className="font-medium">Notification message</label>
            <textarea id="gc-notification-message" aria-describedby="gc-notification-message-limit" required maxLength={NOTIFICATION_BODY_LIMIT} rows={5} value={composer.form.body} placeholder="What do your travellers need to know?" onChange={(event) => composer.change({ ...composer.form, body: event.target.value })} className="min-w-0 resize-y rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600" />
            <p id="gc-notification-message-limit" className="text-xs text-slate-500">{composer.form.body.length}/{NOTIFICATION_BODY_LIMIT} characters</p>
          </div>
        </fieldset>
        <aside className="min-w-0 rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500"><Smartphone className="h-4 w-4" aria-hidden="true" />Phone preview</p>
          <div className="mt-4 rounded-xl border border-white bg-white/90 p-3 shadow-sm" aria-label="Live notification preview">
            <p className="flex items-center gap-2 text-[11px] font-medium text-slate-500"><Bell className="h-3.5 w-3.5 text-blue-600" aria-hidden="true" />GC App <span className="ml-auto">now</span></p>
            <p className="mt-2 break-words text-sm font-semibold text-slate-900">{composer.form.title || "Your notification title"}</p>
            <p className="mt-1 whitespace-pre-wrap break-words text-xs leading-5 text-slate-600">{composer.form.body || "Your message will appear here as you type."}</p>
          </div>
          <p className="mt-3 text-xs leading-5 text-slate-500">Appearance varies by phone. Keep private passenger and document details out of lock-screen alerts.</p>
        </aside>
      </div>
      <div className="border-t border-slate-200 pt-5"><NotificationAudiencePicker agencyId={agencyId} audience={composer.form.audience} groupIds={composer.form.group_ids} groupNames={composer.groupNames} disabled={disabled} onChange={(audience, groupIds) => composer.change({ ...composer.form, audience, group_ids: groupIds })} /></div>
      <p className="text-xs text-slate-500">Saving and reviewing do not send anything. You confirm Send on the review screen.</p>
      {composer.draft?.last_sent_at && <p className="text-xs text-slate-500">Edits apply to future sends. Previously delivered alerts and their history stay unchanged.</p>}
    </div>}
  </GcDialog>;
}

"use client";

import { Button, Card, CardContent, Input } from "@/components/ui";
import { PageHeader } from "@/components/shared/page-header";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import { useGcAppAgencyScope } from "../components/gc-app-agency-scope";
import { GcAlert } from "../components/gc-app-feedback";
import { NotificationAudiencePicker } from "./notification-audience-picker";
import { NotificationDeliverySummary } from "./notification-delivery-summary";
import { NotificationHistory } from "./notification-history";
import { NotificationReviewDialog } from "./notification-review-dialog";
import { NOTIFICATION_BODY_LIMIT, NOTIFICATION_TITLE_LIMIT } from "./notification-types";
import { useNotificationComposer } from "./use-notification-composer";

export function NotificationsPage() {
  const { agencyId } = useGcAppAgencyScope();
  const user = useAuthStore(selectUser);
  if (!agencyId || !user) return null;
  return <NotificationWorkspace key={`${agencyId}:${user.id}`} agencyId={agencyId} actorId={user.id} />;
}

function NotificationWorkspace({ agencyId, actorId }: { agencyId: string; actorId: string }) {
  const composer = useNotificationComposer(agencyId, actorId);
  const disabled = composer.busy || Boolean(composer.pending);
  return <div className="space-y-5">
    <PageHeader title="Notifications" description="Write a phone alert, review the eligible audience, then send it. In-app announcements are managed separately inside each trip." />
    {composer.error && <GcAlert message={composer.error} />}
    {composer.notice && <GcAlert tone="info" message={composer.notice} />}
    {composer.pending && <Card><CardContent className="space-y-3 p-5">
      <h2 className="font-semibold text-slate-900">Check the previous send</h2>
      <p className="text-sm text-slate-600">The response to a send has not been confirmed. Its recovery reference is kept in this browser tab. Check it before starting another notification.</p>
      <div className="flex flex-wrap gap-2"><Button type="button" disabled={composer.busy} onClick={() => void composer.checkPending()}>Check recorded outcome</Button><Button type="button" variant="secondary" disabled={composer.busy} onClick={() => void composer.reviewPending()}>Review and retry same request</Button></div>
    </CardContent></Card>}
    {composer.lastBatch && <NotificationDeliverySummary key={composer.lastBatch.id} agencyId={agencyId} batch={composer.lastBatch} />}
    <Card><CardContent className="space-y-5 p-5">
      <div><h2 className="font-semibold text-slate-900">{composer.resending ? "Prepare another send" : composer.draft ? "Edit saved notification" : "Write a phone notification"}</h2><p className="mt-1 text-sm text-slate-500">This text can appear on a phone&apos;s lock screen. Keep it brief and avoid private passenger or document details.</p></div>
      <fieldset disabled={disabled} className="min-w-0 space-y-4">
        <Input label="Notification title" required maxLength={NOTIFICATION_TITLE_LIMIT} value={composer.form.title} hint={`${composer.form.title.length}/${NOTIFICATION_TITLE_LIMIT} characters`} onChange={(event) => composer.change({ ...composer.form, title: event.target.value })} />
        <div className="flex flex-col gap-1.5 text-sm text-slate-700"><label htmlFor="gc-notification-message" className="font-medium">Notification message</label><textarea id="gc-notification-message" aria-describedby="gc-notification-message-limit" required maxLength={NOTIFICATION_BODY_LIMIT} rows={4} value={composer.form.body} onChange={(event) => composer.change({ ...composer.form, body: event.target.value })} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600" /><p id="gc-notification-message-limit" className="text-xs text-slate-500">{composer.form.body.length}/{NOTIFICATION_BODY_LIMIT} characters</p></div>
      </fieldset>
      <NotificationAudiencePicker agencyId={agencyId} audience={composer.form.audience} groupIds={composer.form.group_ids} groupNames={composer.groupNames} disabled={disabled} onChange={(audience, groupIds) => composer.change({ ...composer.form, audience, group_ids: groupIds })} />
      <div className="flex flex-wrap justify-end gap-2">
        {(composer.hasEdits || composer.draft) && <Button type="button" variant="secondary" disabled={disabled} onClick={composer.discard}>Clear editor</Button>}
        <Button type="button" variant="secondary" disabled={disabled} onClick={() => void composer.save()}>Save draft</Button>
        <Button type="button" disabled={disabled} isLoading={composer.busy} onClick={() => void composer.prepareReview()}>Review audience</Button>
      </div>
      <p className="text-xs text-slate-500">Saving and reviewing do not send anything. You confirm Send on the review screen.</p>
    </CardContent></Card>
    {composer.review && <NotificationReviewDialog draft={composer.review.draft} preview={composer.review.preview} busy={composer.busy} recovering={Boolean(composer.pending)} resending={composer.resending} onClose={composer.closeReview} onRefresh={() => void (composer.pending ? composer.reviewPending() : composer.prepareReview())} onSend={() => void (composer.pending ? composer.retryPending() : composer.send())} />}
    {composer.hasEdits && <p className="text-sm text-slate-500">Save or clear your editor changes before opening another message or preparing a resend.</p>}
    <NotificationHistory agencyId={agencyId} disabled={disabled || composer.hasEdits} onEdit={composer.edit} onResend={composer.resend} onView={composer.selectBatch} />
  </div>;
}

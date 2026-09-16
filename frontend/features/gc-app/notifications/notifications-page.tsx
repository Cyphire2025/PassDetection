"use client";

import Link from "next/link";
import { BellRing, History, Plus } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import { useGcAppAgencyScope } from "../components/gc-app-agency-scope";
import { GcAlert } from "../components/gc-app-feedback";
import { NotificationComposerDialog } from "./notification-composer-dialog";
import { NotificationDeliverySummary } from "./notification-delivery-summary";
import { NotificationReviewDialog } from "./notification-review-dialog";
import { SavedNotifications } from "./saved-notifications";
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
  const modalVisible = composer.editorOpen || Boolean(composer.review);
  return <div className="space-y-6">
    <header className="relative overflow-hidden rounded-2xl border border-blue-100 bg-gradient-to-br from-blue-50 via-white to-sky-50 p-5 sm:p-7">
      <div className="relative flex flex-col justify-between gap-5 lg:flex-row lg:items-center">
        <div className="flex items-start gap-4">
          <span className="rounded-2xl bg-blue-600 p-3 text-white shadow-sm"><BellRing className="h-6 w-6" aria-hidden="true" /></span>
          <div><p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-blue-600">GC App · Phone alerts</p><h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-900">Notifications</h1><p className="mt-2 max-w-lg text-sm leading-6 text-slate-600">Keep travellers informed, wherever they are. Create an alert, choose your trips, and review before sending.</p></div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Link href="/gc-app/notifications/history" className={buttonVariants({ variant: "secondary" })}><History className="h-4 w-4" aria-hidden="true" />History</Link>
          <Button disabled={disabled} onClick={composer.openNew} leftIcon={<Plus className="h-4 w-4" aria-hidden="true" />}>New notification</Button>
        </div>
      </div>
    </header>
    {!modalVisible && composer.error && <GcAlert message={composer.error} />}
    {!modalVisible && composer.notice && <GcAlert tone="info" message={composer.notice} />}
    {composer.pending && <section className="space-y-3 rounded-xl border border-amber-200 bg-amber-50 p-5" aria-labelledby="notification-recovery-title">
      <h2 id="notification-recovery-title" className="font-semibold text-slate-900">Check the previous send</h2>
      <p className="text-sm text-slate-600">The response to a send has not been confirmed. Its recovery reference is kept in this browser tab. Check it before starting another notification.</p>
      <div className="flex flex-wrap gap-2"><Button type="button" disabled={composer.busy} onClick={() => void composer.checkPending()}>Check recorded outcome</Button><Button type="button" variant="secondary" disabled={composer.busy} onClick={() => void composer.reviewPending()}>Review and retry same request</Button></div>
    </section>}
    {composer.lastBatch && <details className="rounded-xl border border-slate-200 bg-white p-4" open><summary className="cursor-pointer text-sm font-semibold text-slate-700">Latest send · delivery status</summary><div className="mt-4"><NotificationDeliverySummary key={composer.lastBatch.id} agencyId={agencyId} batch={composer.lastBatch} /></div></details>}
    <SavedNotifications agencyId={agencyId} actorId={actorId} disabled={disabled || composer.hasEdits} onEdit={composer.edit} onResend={(saved) => saved.last_sent_at ? composer.resendSaved(saved) : composer.edit(saved)} onNew={composer.openNew} />
    <p className="px-1 text-xs leading-5 text-slate-500">Phone notifications are separate from in-app announcements. Manage announcements inside the selected trip.</p>
    {composer.editorOpen && !composer.review && <NotificationComposerDialog agencyId={agencyId} composer={composer} />}
    {composer.review && <NotificationReviewDialog draft={composer.review.draft} preview={composer.review.preview} busy={composer.busy} recovering={Boolean(composer.pending)} resending={composer.resending} error={composer.error} onClose={composer.closeReview} onRefresh={() => void (composer.pending ? composer.reviewPending() : composer.prepareReview())} onSend={() => void (composer.pending ? composer.retryPending() : composer.send())} />}
  </div>;
}

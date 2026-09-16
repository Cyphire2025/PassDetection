"use client";

import { useRef, useState } from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Clock3, FilePenLine, FolderHeart, Globe2, RefreshCw, Send, Trash2, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { GcAlert } from "../components/gc-app-feedback";
import { GcDialog } from "../components/gc-dialog";
import { formatGcDateTime } from "../utils";
import { notificationError } from "./notification-errors";
import { CursorPagination, useCursorPage } from "./notification-pagination";
import type { NotificationDraft } from "./notification-types";
import { notificationsApi } from "./notifications.api";

export function SavedNotifications({ agencyId, actorId, disabled, onEdit, onResend, onNew }: {
  agencyId: string; actorId: string; disabled: boolean;
  onEdit: (draft: NotificationDraft) => void;
  onResend: (draft: NotificationDraft) => void;
  onNew: () => void;
}) {
  const client = useQueryClient();
  const paging = useCursorPage();
  const query = useQuery({ queryKey: ["gc-app", agencyId, "notifications", "drafts", actorId, paging.cursor], queryFn: ({ signal }) => notificationsApi.listDrafts(agencyId, paging.cursor, signal), placeholderData: keepPreviousData });
  const [deleting, setDeleting] = useState<NotificationDraft | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const running = useRef(false);
  const unavailable = disabled || deleteBusy || query.isPlaceholderData || query.isError;
  const remove = async () => {
    if (!deleting || running.current || disabled) return;
    running.current = true; setDeleteBusy(true); setDeleteError(null);
    try {
      await notificationsApi.deleteDraft(agencyId, deleting);
      setDeleting(null); setNotice("Notification removed from Saved. Its send history is still available in History.");
      await client.invalidateQueries({ queryKey: ["gc-app", agencyId, "notifications"] });
    } catch (cause) { setDeleteError(notificationError(cause, "The notification could not be deleted. Refresh Saved and try again.")); }
    finally { running.current = false; setDeleteBusy(false); }
  };
  return <section aria-labelledby="saved-notifications-title" className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
    <header className="flex items-start gap-3 border-b border-slate-100 px-5 py-5 sm:px-6">
      <span className="rounded-xl bg-blue-50 p-2.5 text-blue-600"><FolderHeart className="h-5 w-5" aria-hidden="true" /></span>
      <div><h2 id="saved-notifications-title" className="text-base font-semibold text-slate-900">Saved notifications</h2><p className="mt-1 text-sm text-slate-500">Your drafts and previously sent messages, ready to edit or send again.</p></div>
    </header>
    <div className="space-y-4 p-5 sm:p-6">
      {notice && <GcAlert tone="info" message={notice} />}
      {query.isPending && <p role="status" className="py-8 text-center text-sm text-slate-500">Loading saved notifications…</p>}
      {query.isError && <GcAlert message={notificationError(query.error, "Saved notifications could not be loaded. Use Refresh to try again.")} />}
      {!query.isPending && !query.isError && query.data?.items.length === 0 && <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50/60 px-5 py-12 text-center">
        <Bell className="mx-auto h-8 w-8 text-blue-400" aria-hidden="true" /><h3 className="mt-4 font-semibold text-slate-800">{paging.page === 1 ? "Your next update starts here" : "No more saved notifications"}</h3>
        <p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-slate-500">{paging.page === 1 ? "Create a notification for all active trips or a few selected groups. Every message you send is saved here." : "Go back to the previous page to view earlier messages."}</p>
        {paging.page === 1 && <Button className="mt-5" variant="secondary" disabled={disabled} onClick={onNew}>Create your first notification</Button>}
      </div>}
      <div className="grid gap-4 xl:grid-cols-2" aria-busy={query.isFetching}>
        {query.data?.items.map((draft) => <article key={draft.id} aria-label={draft.title} className="flex min-w-0 flex-col rounded-xl border border-slate-200 p-4 transition-colors hover:border-blue-200 sm:p-5">
          <div className="flex items-center justify-between gap-3"><span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${draft.last_sent_at ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-800"}`}>{draft.last_sent_at ? "Previously sent" : "Draft"}</span>{draft.last_sent_at && draft.status === "draft" && <span className="text-[11px] text-slate-500">Edited since last send</span>}</div>
          <h3 className="mt-3 break-words font-semibold text-slate-900">{draft.title}</h3>
          <p className="mt-1.5 whitespace-pre-wrap break-words text-sm leading-6 text-slate-600">{draft.body}</p>
          <div className="mt-4 space-y-2 text-xs text-slate-500">
            <p className="flex items-start gap-2">{draft.audience === "all_active_trips" ? <Globe2 className="h-4 w-4 shrink-0 text-blue-500" aria-hidden="true" /> : <Users className="h-4 w-4 shrink-0 text-blue-500" aria-hidden="true" />}<span className="break-words">{draft.audience === "all_active_trips" ? "All active trips at send time" : draft.group_names?.length ? draft.group_names.join(" · ") : `${draft.group_ids.length} selected groups`}</span></p>
            <p className="flex items-start gap-2"><Clock3 className="h-4 w-4 shrink-0" aria-hidden="true" /><span>{draft.last_sent_at ? `Last sent ${formatGcDateTime(draft.last_sent_at)}` : `Saved ${formatGcDateTime(draft.created_at)}`}</span></p>
          </div>
          <div className="mt-auto pt-5"><div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-4">
            <Button size="sm" disabled={unavailable} onClick={() => onResend(draft)} leftIcon={draft.last_sent_at ? <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" /> : <Send className="h-3.5 w-3.5" aria-hidden="true" />}>{draft.last_sent_at ? "Resend" : "Review & send"}</Button>
            <Button size="sm" variant="secondary" disabled={unavailable} onClick={() => onEdit(draft)} leftIcon={<FilePenLine className="h-3.5 w-3.5" aria-hidden="true" />}>Edit</Button>
            <Button size="sm" variant="ghost" className="ml-auto text-red-600 hover:bg-red-50 hover:text-red-700" disabled={unavailable} onClick={() => { setDeleting(draft); setDeleteError(null); }} leftIcon={<Trash2 className="h-3.5 w-3.5" aria-hidden="true" />}>Delete</Button>
          </div></div>
        </article>)}
      </div>
      <CursorPagination page={paging.page} nextCursor={query.data?.next_cursor ?? null} itemCount={query.data?.items.length} disabled={query.isFetching || deleteBusy} previous={paging.previous} next={paging.next} onRefresh={() => void query.refetch()} />
    </div>
    {deleting && <GcDialog open title="Delete saved notification?" description="Remove this message from Saved notifications." size="md" closeDisabled={deleteBusy} onClose={() => { if (!deleteBusy) setDeleting(null); }} footer={<><Button variant="secondary" disabled={deleteBusy} onClick={() => setDeleting(null)}>Keep notification</Button><Button variant="danger" isLoading={deleteBusy} disabled={disabled} onClick={() => void remove()}>Delete notification</Button></>}>
      <div className="space-y-3">{deleteError && <GcAlert message={deleteError} />}<p className="break-words font-medium text-slate-900">{deleting.title}</p><p className="text-sm leading-6 text-slate-600">Its send history will stay in History. Alerts already sent or queued will continue; deleting the saved message does not recall them.</p></div>
    </GcDialog>}
  </section>;
}

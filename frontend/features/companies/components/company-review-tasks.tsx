"use client";

import { useId, useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { WorkspaceEmptyState } from "@/components/shared/workspace-ui";
import { ROUTES } from "@/constants/routes";
import { companyReviewTasksApi, type CompanyReviewTask, type ReviewTaskStatus } from "../api/company-review-tasks.api";
import { companyKeys } from "../hooks/use-companies";
import { CompanyError, CompanyLoading, CompanyPagination, companyErrorMessage } from "./company-feedback";

export function CompanyReviewTasks({ agencyId, companyId }: { agencyId: string; companyId: string }) {
  const [status, setStatus] = useState<ReviewTaskStatus | "all">("pending");
  const [cursor, setCursor] = useState<string>();
  const [selected, setSelected] = useState<CompanyReviewTask | null>(null);
  const tasks = useQuery({
    queryKey: [...companyKeys.scope(agencyId), companyId, "review-tasks", status, cursor],
    queryFn: ({ signal }) => companyReviewTasksApi.list(agencyId, companyId, status, cursor, signal),
    staleTime: 0, gcTime: 0, retry: 1,
  });
  return <div className="space-y-3">
    <p className="text-sm leading-6 text-slate-600">Review the effect of document changes on tickets, visas and manifests. These tasks record your team’s review; external systems must be checked separately. Historical trip documents remain preserved.</p>
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
      <div className="border-b border-slate-100 p-4"><label htmlFor="review-task-status" className="mr-3 text-sm font-medium text-slate-700">Task status</label><select id="review-task-status" value={status} onChange={(event) => { setStatus(event.target.value as ReviewTaskStatus | "all"); setCursor(undefined); }} className="min-h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm focus-visible:ring-2 focus-visible:ring-blue-600"><option value="pending">Pending</option><option value="resolved">Resolved</option><option value="dismissed">Dismissed</option><option value="all">All tasks</option></select><Button type="button" variant="secondary" className="ml-3 mt-2 min-h-11 sm:mt-0" disabled={tasks.isFetching} onClick={() => void tasks.refetch()}>Refresh tasks</Button></div>
      {tasks.isLoading ? <CompanyLoading /> : tasks.isError ? <CompanyError message="Review tasks could not be loaded." retry={() => void tasks.refetch()} /> : !tasks.data?.items.length ? <WorkspaceEmptyState title="No review tasks in this view" description="Document changes that need operational review will appear here." /> : <ul className="divide-y divide-slate-100">{tasks.data.items.map((task) => <li key={task.id} className="space-y-3 p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3"><h3 className="text-sm font-semibold text-slate-900">Document change review</h3><span className={`rounded-full px-2 py-1 text-xs capitalize ${task.status === "pending" ? "bg-amber-50 text-amber-800" : "bg-slate-100 text-slate-600"}`}>{task.status}</span></div>
        <p className="break-words text-xs leading-5 text-slate-500">{task.reason_code.replaceAll("_", " ").toLowerCase()} · Created {new Date(task.created_at).toLocaleDateString()}</p>
        <dl className="grid gap-2 text-xs text-slate-600 sm:grid-cols-2"><div><dt className="font-medium">Previous document revision</dt><dd className="mt-1 break-all">{task.old_document_revision_id}</dd></div><div><dt className="font-medium">New document revision</dt><dd className="mt-1 break-all">{task.new_document_revision_id ?? "Document withdrawn or unavailable"}</dd></div></dl>
        {task.resolution_reason && <p className="break-words text-sm leading-6 text-slate-700">Review note: {task.resolution_reason}</p>}
        <div className="flex flex-wrap items-center gap-4"><Link className="text-sm font-medium text-blue-700 underline focus-visible:ring-2 focus-visible:ring-blue-600" href={ROUTES.dashboard.passportGroup(task.group_id)}>Open affected group</Link>{task.source_submission_id && <Link className="text-sm font-medium text-blue-700 underline focus-visible:ring-2 focus-visible:ring-blue-600" href={ROUTES.dashboard.passportDetail(task.source_submission_id)}>Review trip submission</Link>}{task.status === "pending" && <Button type="button" variant="secondary" className="min-h-11" onClick={() => setSelected(task)}>Record review outcome</Button>}</div>
      </li>)}</ul>}
      <CompanyPagination cursor={cursor} hasMore={tasks.data?.has_more ?? false} nextCursor={tasks.data?.next_cursor ?? null} pending={tasks.isFetching} onChange={setCursor} />
    </div>
    {selected && <ReviewTaskDialog key={selected.id} agencyId={agencyId} companyId={companyId} task={selected} onClose={() => setSelected(null)} />}
  </div>;
}

function ReviewTaskDialog({ agencyId, companyId, task, onClose }: { agencyId: string; companyId: string; task: CompanyReviewTask; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [resolution, setResolution] = useState<"resolved" | "dismissed">("resolved");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const mutation = useMutation({
    mutationFn: () => companyReviewTasksApi.resolve(agencyId, companyId, task.id, { expected_revision: task.revision, expected_participation_revision: task.current_participation_revision, resolution, reason: reason.trim() }),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: companyKeys.scope(agencyId) }); onClose(); },
  });
  const dialogRef = useRef<HTMLDivElement>(null);
  const title = useId();
  const keyboard = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: !mutation.isPending, onClose });
  return <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={title} onKeyDown={keyboard} className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"><section className="max-h-[90dvh] w-full max-w-lg space-y-4 overflow-y-auto rounded-2xl bg-white p-5 shadow-xl"><h2 id={title} className="text-lg font-semibold text-slate-950">Record document review</h2>
    <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); if (!mutation.isPending && confirmed && reason.trim().length >= 10) mutation.mutate(); }}>
      <p className="text-sm leading-6 text-slate-600">Check the affected tickets, visas and manifests before resolving this task. Dismiss only when you have established that no action is needed.</p>
      <label className="block text-sm font-medium text-slate-700">Outcome<select value={resolution} disabled={mutation.isPending} onChange={(event) => setResolution(event.target.value as "resolved" | "dismissed")} className="mt-2 min-h-11 w-full rounded-lg border border-slate-300 bg-white px-3"><option value="resolved">Resolved — checks completed</option><option value="dismissed">Dismissed — no action needed</option></select></label>
      <label className="block text-sm font-medium text-slate-700">Review note<textarea required minLength={10} maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} disabled={mutation.isPending} className="mt-2 min-h-28 w-full rounded-lg border border-slate-300 p-3" /><span className="text-xs font-normal text-slate-500">10–500 characters describing the checks and outcome.</span></label>
      <label className="flex items-start gap-3 text-sm leading-6 text-slate-700"><input type="checkbox" className="mt-1" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} disabled={mutation.isPending} />I reviewed the affected trip and recorded the outcome accurately.</label>
      {mutation.isError && <CompanyError message={companyErrorMessage(mutation.error, "The task or trip may have changed. Close this form, refresh the list and review again.")} />}
      <div className="flex flex-wrap justify-end gap-3"><Button type="button" variant="secondary" onClick={onClose} disabled={mutation.isPending}>Cancel</Button><Button type="submit" disabled={!confirmed || reason.trim().length < 10} isLoading={mutation.isPending}>Save review outcome</Button></div>
    </form>
  </section></div>;
}

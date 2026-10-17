"use client";

import { useId, useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { ROUTES } from "@/constants/routes";
import { companyMatchingApi, MATCH_CASE_STATUSES, type MatchCaseStatus, type TravellerMatchCase } from "../api/company-matching.api";
import { companyKeys } from "../hooks/use-companies";
import type { CompanyGroup } from "../types";
import { CompanyError, CompanyLoading, CompanyPagination, companyErrorMessage } from "./company-feedback";
import { CompanyMatchResolution, PROFILE_ID_PATTERN } from "./company-match-resolution";

export function CompanyMatchingDialog({ agencyId, companyId, group, onClose }: { agencyId: string; companyId: string; group: CompanyGroup; onClose: () => void }) {
  const [status, setStatus] = useState<MatchCaseStatus | "all">("all");
  const [cursor, setCursor] = useState<string>();
  const [selected, setSelected] = useState<{ match: TravellerMatchCase; groupRevision: number } | null>(null);
  const [decisionPending, setDecisionPending] = useState(false);
  const [requestKey, setRequestKey] = useState(() => crypto.randomUUID());
  const client = useQueryClient();
  const query = useQuery({ queryKey: [...companyKeys.scope(agencyId), companyId, group.id, "matching-preview", status, cursor], queryFn: ({ signal }) => companyMatchingApi.preview(agencyId, companyId, group.id, status, cursor, signal), staleTime: 0, gcTime: 0, retry: 1 });
  const enqueue = useMutation({ mutationFn: () => companyMatchingApi.enqueue(agencyId, companyId, group.id, requestKey), onSuccess: async () => { setRequestKey(crypto.randomUUID()); await client.invalidateQueries({ queryKey: [...companyKeys.scope(agencyId), companyId, group.id, "matching-preview"] }); } });
  const pending = decisionPending || enqueue.isPending;
  const dialogRef = useRef<HTMLDivElement>(null);
  const title = useId();
  const keyboard = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: !pending, onClose });
  const jobStatus = query.data?.latest_job_status ?? enqueue.data?.status;
  const jobActive = jobStatus === "queued" || jobStatus === "running" || jobStatus === "retrying";
  const refresh = () => { setSelected(null); void query.refetch(); };
  return <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={title} onKeyDown={keyboard} className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-3 sm:p-5"><section className="max-h-[90dvh] w-full max-w-2xl space-y-4 overflow-y-auto rounded-2xl bg-white p-4 shadow-xl sm:p-5">
    <div className="flex items-start justify-between gap-3"><div><h2 id={title} className="text-lg font-semibold text-slate-950">Review traveller matches</h2><p className="mt-1 break-words text-sm text-slate-500">{group.name}</p></div><Button type="button" variant="ghost" onClick={onClose} disabled={pending}>Close</Button></div>
    <p className="text-sm leading-6 text-slate-600">Matching prepares review cases in the background. Cases and counts describe records, not confirmed unique people. Roster decisions do not grant document access or complete a trip submission.</p>
    <Link target="_blank" rel="noopener noreferrer" href={ROUTES.dashboard.passportGroup(group.id)} className="inline-block text-sm font-medium text-blue-700 underline focus-visible:ring-2 focus-visible:ring-blue-600">Open source group</Link>
    {query.isLoading ? <CompanyLoading /> : query.isError || !query.data ? <CompanyError message={companyErrorMessage(query.error, "Matching cases are unavailable or you no longer have access.")} retry={() => void query.refetch()} /> : <>
      <div className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-3"><p role="status" className="text-sm leading-6 text-slate-700">{jobStatus ? `Latest matching job: ${jobStatus}. ${query.data.processed_count.toLocaleString()} source records processed.` : "No matching job has been requested."}{jobActive ? " Processing runs in the background. Refresh this preview to see progress." : ""}</p><div className="flex flex-wrap gap-2"><Button type="button" variant="secondary" className="h-auto min-h-11 whitespace-normal" disabled={pending || jobActive || Boolean(selected)} onClick={() => enqueue.mutate()}>Run matching preview</Button><Button type="button" variant="secondary" className="min-h-11" disabled={pending || query.isFetching} onClick={refresh}>Refresh preview</Button></div>{enqueue.isError && <CompanyError message={companyErrorMessage(enqueue.error, "The matching job could not be queued. Retry safely.")} />}</div>
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3" aria-label="Matching case counts">{MATCH_CASE_STATUSES.map((item) => <div key={item} className="rounded-lg border border-slate-200 p-3"><dt className="text-xs capitalize text-slate-500">{item} records</dt><dd className="mt-1 text-lg font-semibold tabular-nums text-slate-900">{(query.data.counts[item] ?? 0).toLocaleString()}</dd></div>)}</dl>
      {selected ? <><MatchSource match={selected.match} /><CompanyMatchResolution key={selected.match.id} agencyId={agencyId} companyId={companyId} groupId={group.id} match={selected.match} groupRevision={selected.groupRevision} onPending={setDecisionPending} onBack={() => setSelected(null)} onRefresh={refresh} /></> : <>
        <label className="block text-sm font-medium text-slate-700">Case status<select value={status} disabled={pending} onChange={(event) => { setStatus(event.target.value as MatchCaseStatus | "all"); setCursor(undefined); }} className="mt-2 min-h-11 w-full rounded-lg border border-slate-300 bg-white px-3"><option value="all">All cases</option>{MATCH_CASE_STATUSES.map((item) => <option key={item} value={item}>{item.charAt(0).toUpperCase() + item.slice(1)}</option>)}</select></label>
        <ul className="space-y-3">{query.data.items.map((match) => <li key={match.id} className="space-y-3 rounded-xl border border-slate-200 p-3"><MatchSource match={match} /><div className="flex flex-wrap items-center justify-between gap-2"><span className="rounded-full bg-slate-100 px-2 py-1 text-xs capitalize text-slate-700">{match.status}</span>{match.status !== "resolved" && match.status !== "purged" && <Button type="button" variant="secondary" className="min-h-11" disabled={query.isFetching || pending} onClick={() => setSelected({ match, groupRevision: query.data.expected_group_revision })}>Review association</Button>}</div></li>)}</ul>
        {!query.data.items.length && <p className="rounded-xl border border-dashed border-slate-300 p-4 text-sm leading-6 text-slate-500">No matching cases in this view. Run a preview for the group, or choose another status after processing.</p>}
        <CompanyPagination cursor={cursor} hasMore={Boolean(query.data.next_cursor)} nextCursor={query.data.next_cursor} pending={query.isFetching || pending} onChange={setCursor} />
      </>}
    </>}
  </section></div>;
}

function MatchSource({ match }: { match: TravellerMatchCase }) {
  return <div className="space-y-2 text-xs leading-5 text-slate-600"><p className="break-words text-sm font-medium text-slate-900">{match.reason_code.replaceAll("_", " ")}</p><p>Source: {match.source_kind.replaceAll("_", " ")}</p><p className="break-all">Source reference: {match.source_row_key}</p>{match.source_kind === "passport_submission" && PROFILE_ID_PATTERN.test(match.source_row_key) && <Link target="_blank" rel="noopener noreferrer" href={ROUTES.dashboard.passportDetail(match.source_row_key)} className="inline-block text-sm font-medium text-blue-700 underline focus-visible:ring-2 focus-visible:ring-blue-600">Review source submission</Link>}</div>;
}

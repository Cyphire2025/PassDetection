"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, RefreshCw, UserRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { WorkspaceToolbar } from "@/components/shared/workspace-ui";
import { useDebounce } from "@/hooks/use-debounce";
import { companyPeopleApi } from "../api/company-people.api";
import { useCompanyQueryContext } from "../hooks/use-companies";
import { CompanyError, CompanyLoading, CompanyPagination } from "./company-feedback";
import { CompanyDataExports } from "./company-data-exports";

const CompanyPersonDialog = dynamic(() => import("./company-person-dialog").then((module) => module.CompanyPersonDialog));
const CompanyMatchQueue = dynamic(() => import("./company-match-queue").then((module) => module.CompanyMatchQueue));

/** One 25-person page; personal fields and document bytes load only on Open. */
export function CompanyAllData({ agencyId, companyId }: { agencyId: string; companyId: string }) {
  const { scope, ready } = useCompanyQueryContext(agencyId);
  const [search, setSearch] = useState("");
  const term = useDebounce(search.trim(), 250);
  const [cursor, setCursor] = useState<string>();
  const [selected, setSelected] = useState<string>();
  const [reviewMatches, setReviewMatches] = useState(false);
  const settled = search.trim() === term;
  const people = useQuery({ queryKey: [...scope, companyId, "people", term, cursor], queryFn: ({ signal }) => companyPeopleApi.list(agencyId, companyId, { search: term, cursor }, signal), enabled: ready && settled, staleTime: 0, gcTime: 0, refetchOnWindowFocus: false, retry: false });
  return <div className="space-y-4">
    <div className="flex flex-wrap items-start justify-between gap-3"><CompanyDataExports agencyId={agencyId} companyId={companyId} /><Button type="button" variant="secondary" disabled={!ready || people.isError} onClick={() => { setSelected(undefined); setReviewMatches(true); }}>Review matches</Button></div>
    {ready && !people.isError && people.data?.indexing_pending && <p role="status" className="text-xs text-slate-500">Preparing saved records. More people may appear shortly.</p>}
    <section aria-label="Company people" className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <WorkspaceToolbar query={search} onQueryChange={(value) => { setSearch(value); setCursor(undefined); setSelected(undefined); }} searchLabel="Search company people" placeholder="Search full name or ID"><Button type="button" variant="ghost" size="icon" aria-label="Refresh people" disabled={!ready || people.isFetching} onClick={() => void people.refetch()}><RefreshCw className={`h-4 w-4 ${people.isFetching ? "motion-safe:animate-spin" : ""}`} aria-hidden="true" /></Button></WorkspaceToolbar>
      {!ready || !settled || people.isLoading ? <CompanyLoading /> : people.isError ? <CompanyError message="People could not be loaded." retry={() => void people.refetch()} /> : people.data?.items.length ? <ul className="divide-y divide-slate-100">{people.data.items.map((person) => <li key={person.id} className="flex items-center gap-3 px-4 py-4 sm:px-5">
        <span className="hidden h-10 w-10 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-500 sm:flex"><UserRound className="h-4 w-4" aria-hidden="true" /></span>
        <div className="min-w-0 flex-1"><p className="break-words text-sm font-semibold text-slate-950">{person.display_name}</p><p className="mt-1 text-xs leading-5 text-slate-500">{person.trip_count.toLocaleString()} {person.trip_count === 1 ? "trip" : "trips"} · {person.document_version_count.toLocaleString()} {person.document_version_count === 1 ? "document version" : "document versions"}{person.current_passport_last4 ? ` · ••••${person.current_passport_last4}` : ""}</p>{person.duplicate_status === "possible" && <span className="mt-1 inline-flex rounded-md bg-amber-50 px-1.5 py-0.5 text-xs font-medium text-amber-800">Possible duplicate</span>}</div>
        <Button type="button" variant="secondary" size="sm" className="min-h-11 shrink-0 text-blue-700" aria-label={`Open ${person.display_name}`} onClick={() => setSelected(person.id)}>Open<ArrowRight className="h-3.5 w-3.5" aria-hidden="true" /></Button>
      </li>)}</ul> : <p className="px-4 py-8 text-sm text-slate-500">{people.data?.indexing_pending ? "Saved records are being prepared." : term ? "No matching people. Try the full name or ID." : "No people yet."}</p>}
      {(cursor || people.data?.has_more) && !people.isError && <CompanyPagination cursor={cursor} hasMore={people.data?.has_more ?? false} nextCursor={people.data?.next_cursor ?? null} pending={!ready || !settled || people.isFetching} onChange={(value) => { setCursor(value); setSelected(undefined); }} />}
    </section>
    {ready && !people.isError && selected && <CompanyPersonDialog key={`${scope.join(":")}:${selected}`} agencyId={agencyId} companyId={companyId} personId={selected} onClose={() => setSelected(undefined)} />}
    {ready && !people.isError && reviewMatches && <CompanyMatchQueue key={scope.join(":")} agencyId={agencyId} companyId={companyId} onClose={() => setReviewMatches(false)} />}
  </div>;
}

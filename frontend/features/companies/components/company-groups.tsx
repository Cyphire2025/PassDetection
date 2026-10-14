"use client";

import Link from "next/link";
import { ArrowRight, CalendarDays, MapPin, RefreshCw } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { WorkspaceToolbar } from "@/components/shared/workspace-ui";
import { useDebounce } from "@/hooks/use-debounce";
import { useCompanyGroups } from "../hooks/use-companies";
import type { CompanyGroup } from "../types";
import { CompanyError, CompanyLoading, CompanyPagination } from "./company-feedback";
import { useCompanyViewState } from "../hooks/use-company-view-state";
import { companyGroupHref, companyViewHref } from "../utils/company-navigation";

export function CompanyGroups({ agencyId, companyId }: { agencyId: string; companyId: string }) {
  const view = useCompanyViewState();
  const search = view.params.get("groupSearch") ?? "";
  const debounced = useDebounce(search, 250);
  return <div className="space-y-4">
    <div className="overflow-hidden rounded-xl border border-slate-200"><WorkspaceToolbar query={search} onQueryChange={(value) => view.update({ groupSearch: value, activeCursor: undefined, completedCursor: undefined })} searchLabel="Search company groups" placeholder="Search groups" /></div>
    {(["active", "completed"] as const).map((phase) => <GroupSection key={`${phase}:${debounced}`} agencyId={agencyId} companyId={companyId} phase={phase} search={debounced} changingSearch={search !== debounced} />)}
  </div>;
}

function GroupSection({ agencyId, companyId, phase, search, changingSearch }: { agencyId: string; companyId: string; phase: "active" | "completed"; search: string; changingSearch: boolean }) {
  const view = useCompanyViewState();
  const cursorKey = `${phase}Cursor`;
  const cursor = view.params.get(cursorKey) ?? undefined;
  const groups = useCompanyGroups(agencyId, companyId, { phase, search, cursor, page_size: 25 });
  const label = phase === "active" ? "Active groups" : "Completed groups";
  return <section aria-label={label} className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
    <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-2 sm:px-5"><h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900"><span className={`h-2 w-2 rounded-full ${phase === "active" ? "bg-blue-500" : "bg-emerald-500"}`} aria-hidden="true" />{label}</h2><Button type="button" size="icon" variant="ghost" aria-label={`Refresh ${label.toLowerCase()}`} disabled={groups.isFetching} onClick={() => void groups.refetch()}><RefreshCw className={`h-3.5 w-3.5 ${groups.isFetching ? "motion-safe:animate-spin" : ""}`} aria-hidden="true" /></Button></div>
    {groups.isLoading || changingSearch ? <CompanyLoading /> : groups.isError ? <CompanyError message="Groups could not be loaded." retry={() => void groups.refetch()} /> : groups.data?.items.length ? <ul className="divide-y divide-slate-100">{groups.data.items.map((group) => <GroupRow key={group.id} group={group} returnTo={companyViewHref(companyId, view.query)} />)}</ul> : <p className="px-4 py-6 text-sm text-slate-500">{search ? "No matching groups." : `No ${phase} groups yet.`}</p>}
    {(cursor || groups.data?.has_more) && !groups.isError && <CompanyPagination cursor={cursor} hasMore={groups.data?.has_more ?? false} nextCursor={groups.data?.next_cursor ?? null} pending={groups.isFetching || changingSearch} onChange={(value) => view.update({ [cursorKey]: value })} />}
  </section>;
}

function GroupRow({ group, returnTo }: { group: CompanyGroup; returnTo: string }) {
  return <li className="flex items-center gap-3 px-4 py-4 sm:px-5">
    <div className="min-w-0 flex-1"><h3 className="break-words text-sm font-semibold text-slate-950">{group.name}</h3><div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-xs leading-5 text-slate-500">{group.destination && <span className="inline-flex min-w-0 items-start gap-1"><MapPin className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" /><span className="break-words">{group.destination}</span></span>}{group.travel_date && <span className="inline-flex items-start gap-1"><CalendarDays className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />{group.travel_date}{group.return_date ? ` – ${group.return_date}` : ""}</span>}<span>{group.submission_count.toLocaleString()} records</span></div></div>
    <Link prefetch={false} href={companyGroupHref(group.id, returnTo)} aria-label={`View ${group.name}`} className={buttonVariants({ variant: "secondary", size: "sm", className: "min-h-11 shrink-0 gap-1.5 text-blue-700" })}>View<ArrowRight className="h-3.5 w-3.5" aria-hidden="true" /></Link>
  </li>;
}

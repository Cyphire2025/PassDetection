"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import dynamic from "next/dynamic";
import { Archive, ArrowLeft, Building2, CalendarDays, CheckCircle2, Users } from "lucide-react";
import { WorkspaceEmptyState, WorkspacePageHeader, WorkspaceSummaryItem, WorkspaceSummaryStrip, WorkspaceToolbar } from "@/components/shared/workspace-ui";
import { ROUTES } from "@/constants/routes";
import { useDebounce } from "@/hooks/use-debounce";
import { useCompany, useCompanyGroups, useCompanySummary } from "../hooks/use-companies";
import type { CompanyGroup, CompanyGroupSearch } from "../types";
import { useCompanyAgency } from "./company-agency-scope";
import { CompanyError, CompanyLoading, CompanyPagination } from "./company-feedback";
import { CompanyTravellers } from "./company-travellers";
import { CompanyReusePolicy } from "./company-reuse-policy";
import { GroupReuseDialog } from "./group-reuse-dialog";
import { TravellerEnrollmentDialog } from "./traveller-enrollment-dialog";
import { CompanyReviewTasks } from "./company-review-tasks";

const COMPANY_TABS = ["groups", "records", "travellers", "review"] as const;
const CompanyMatchingDialog = dynamic(() => import("./company-matching-dialog").then((module) => module.CompanyMatchingDialog));
const CompanyCollectedRecords = dynamic(() => import("./company-collected-records").then((module) => module.CompanyCollectedRecords), { loading: () => <CompanyLoading /> });

export function CompanyDashboard({ companyId }: { companyId: string }) {
  const agencyId = useCompanyAgency();
  const company = useCompany(agencyId, companyId);
  const summary = useCompanySummary(agencyId, companyId);
  const [tab, setTab] = useState<typeof COMPANY_TABS[number]>("groups");
  if (company.isLoading) return <CompanyLoading />;
  if (company.isError || !company.data) return <CompanyError message="This company is unavailable or you no longer have access." retry={() => void company.refetch()} />;

  return <div className="min-w-0 space-y-5">
    <Link href={ROUTES.dashboard.companies} className="inline-flex items-center gap-2 rounded text-sm font-medium text-slate-600 focus-visible:ring-2 focus-visible:ring-blue-600"><ArrowLeft className="h-4 w-4" aria-hidden="true" />Companies / Clients</Link>
    <WorkspacePageHeader title={company.data.name} description="Combined records and traveller history from all groups assigned to this client company." icon={Building2} context={<span className={`rounded-full px-3 py-1 text-xs font-medium ${company.data.status === "active" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-800"}`}>{company.data.status === "active" ? "Active company" : "Inactive · historical views available"}</span>} />
    {summary.isError ? <CompanyError message="Company totals could not be loaded." retry={() => void summary.refetch()} /> : summary.data ? <>
      <WorkspaceSummaryStrip label="All visible company groups">
        <WorkspaceSummaryItem label="Active groups" value={summary.data.active_groups.toLocaleString()} icon={CalendarDays} tone="success" />
        <WorkspaceSummaryItem label="Closed groups" value={summary.data.closed_groups.toLocaleString()} icon={CheckCircle2} />
        <WorkspaceSummaryItem label="Archived groups" value={summary.data.archived_groups.toLocaleString()} icon={Archive} />
        <WorkspaceSummaryItem label="Total groups" value={summary.data.total_groups.toLocaleString()} icon={Building2} />
      </WorkspaceSummaryStrip>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <IdentityMetric label="Collected records" value={summary.data.collected_records} hint="Submissions across assigned groups, including records awaiting identity resolution." />
        <IdentityMetric label={`Unique travellers${summary.data.identity_totals_partial ? " · partial" : ""}`} value={summary.data.unique_travellers} hint="Distinct resolved people with accepted participation." />
        <IdentityMetric label="Trip participations" value={summary.data.trip_participations} hint="One person on five trips counts as five participations." />
        <IdentityMetric label="Unresolved historical records" value={summary.data.unresolved_historical_records} hint="Records awaiting safe identity resolution; these are not additional unique people." />
      </div>
      <p className="text-xs leading-5 text-slate-500">Totals combine all assigned groups you can view. Total groups = active + closed + archived. Import-only is a filter within these categories. Deleted and Old Data records are excluded.{summary.data.identity_totals_partial ? ` Traveller totals remain partial while history is reconciled.${summary.data.unprocessed_records !== undefined ? ` ${summary.data.unprocessed_records.toLocaleString()} records are unprocessed.` : ""}` : ""}</p>
    </> : <CompanyLoading />}
    <CompanyReusePolicy agencyId={agencyId} companyId={companyId} active={company.data.status === "active"} />
    <div className="flex flex-wrap gap-2 border-b border-slate-200" role="tablist" aria-label="Company views">
      {COMPANY_TABS.map((item, index) => <button key={item} type="button" role="tab" id={`company-${item}-tab`} aria-controls={`company-${item}-panel`} aria-selected={tab === item} tabIndex={tab === item ? 0 : -1}
        onKeyDown={(event) => { if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); const next = COMPANY_TABS[(index + (event.key === "ArrowRight" ? 1 : -1) + COMPANY_TABS.length) % COMPANY_TABS.length]; setTab(next); document.getElementById(`company-${next}-tab`)?.focus(); } }}
        onClick={() => setTab(item)} className={`min-h-11 border-b-2 px-3 py-3 text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 ${tab === item ? "border-blue-600 text-blue-700" : "border-transparent text-slate-500"}`}>{item === "groups" ? "Groups" : item === "records" ? "Collected records" : item === "travellers" ? "Travellers & history" : "Review tasks"}</button>)}
    </div>
    <section role="tabpanel" id={`company-${tab}-panel`} aria-labelledby={`company-${tab}-tab`}>
      {tab === "groups" ? <CompanyGroups agencyId={agencyId} companyId={companyId} /> : tab === "records" ? <CompanyCollectedRecords agencyId={agencyId} companyId={companyId} /> : tab === "travellers" ? <CompanyTravellers agencyId={agencyId} companyId={companyId} /> : <CompanyReviewTasks agencyId={agencyId} companyId={companyId} />}
    </section>
  </div>;
}

function IdentityMetric({ label, value, hint }: { label: string; value: number | null; hint: string }) {
  return <div className="rounded-xl border border-slate-200 bg-white p-4"><p className="text-xs font-medium text-slate-500">{label}</p><p className="mt-2 text-xl font-semibold tabular-nums text-slate-950">{value === null ? "Pending reconciliation" : value.toLocaleString()}</p><p className="mt-2 text-xs leading-5 text-slate-500">{hint}</p></div>;
}

function CompanyGroups({ agencyId, companyId }: { agencyId: string; companyId: string }) {
  const [search, setSearch] = useState("");
  const debounced = useDebounce(search, 250);
  const [status, setStatus] = useState<CompanyGroupSearch["status"]>("all");
  const [mode, setMode] = useState("all");
  const [cursor, setCursor] = useState<string>();
  const [selectedGroup, setSelectedGroup] = useState<CompanyGroup | null>(null);
  const [enrollmentGroup, setEnrollmentGroup] = useState<CompanyGroup | null>(null);
  const [matchingGroup, setMatchingGroup] = useState<CompanyGroup | null>(null);
  const groups = useCompanyGroups(agencyId, companyId, { search: debounced, status, import_only: mode === "all" ? undefined : mode === "import", cursor, page_size: 25 });
  return <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
    <WorkspaceToolbar query={search} onQueryChange={(value) => { setSearch(value); setCursor(undefined); }} searchLabel="Search company groups" placeholder="Search groups">
      <select aria-label="Group lifecycle" value={status} onChange={(event) => { setStatus(event.target.value as CompanyGroupSearch["status"]); setCursor(undefined); }} className="min-h-10 rounded-lg border border-slate-300 px-2 text-sm focus-visible:ring-2 focus-visible:ring-blue-600"><option value="all">All lifecycle states</option><option value="active">Active</option><option value="closed">Closed</option><option value="archived">Archived</option></select>
      <select aria-label="Group collection mode" value={mode} onChange={(event) => { setMode(event.target.value); setCursor(undefined); }} className="min-h-10 rounded-lg border border-slate-300 px-2 text-sm focus-visible:ring-2 focus-visible:ring-blue-600"><option value="all">All group modes</option><option value="collection">Collection</option><option value="import">Import-only</option></select>
    </WorkspaceToolbar>
    {groups.isLoading || search !== debounced ? <CompanyLoading /> : groups.isError ? <CompanyError message="Company groups could not be loaded." retry={() => void groups.refetch()} /> : groups.data?.items.length ? <ul className="divide-y divide-slate-100">{groups.data.items.map((group) => <li key={group.id} className="flex flex-col justify-between gap-3 p-4 sm:flex-row sm:items-center sm:p-5">
      <div className="min-w-0"><Link href={ROUTES.dashboard.passportGroup(group.id)} className="break-words text-sm font-semibold text-blue-800 hover:underline focus-visible:ring-2 focus-visible:ring-blue-600">{group.name}</Link><p className="mt-1 break-words text-xs leading-5 text-slate-500">{group.destination ?? "Destination not set"} · {group.travel_date ?? "Date not set"}{group.return_date ? ` – ${group.return_date}` : ""}</p><div className="mt-2 flex flex-wrap gap-2 text-xs"><span className="rounded-full bg-slate-100 px-2 py-1 capitalize text-slate-700">{group.status}</span><span className="rounded-full bg-blue-50 px-2 py-1 text-blue-700">{group.import_only ? "Import-only" : "Collection"}</span></div><p className="mt-2 text-xs leading-5 text-slate-500">{group.returning_travellers ?? "–"} returning travellers · {group.trip_participations ?? "–"} accepted participations · {group.reuse_completed ?? "–"} completed reuse</p></div>
      <div className="flex min-w-0 flex-wrap items-center gap-3 sm:max-w-[55%] sm:justify-end"><span className="flex items-center gap-2 text-xs text-slate-600"><Users className="h-4 w-4" aria-hidden="true" />{group.submission_count.toLocaleString()} submissions</span><Button type="button" variant="secondary" size="sm" className="min-h-11" onClick={() => setSelectedGroup(group)}>Reuse settings</Button><Button type="button" variant="secondary" size="sm" className="min-h-11" onClick={() => setEnrollmentGroup(group)}>Enroll accepted traveller</Button><Button type="button" variant="secondary" size="sm" className="min-h-11" onClick={() => setMatchingGroup(group)}>Review matches</Button></div>
    </li>)}</ul> : <WorkspaceEmptyState title="No groups in this view" description="Try different filters or assign a group through Group Links." />}
    <CompanyPagination cursor={cursor} hasMore={groups.data?.has_more ?? false} nextCursor={groups.data?.next_cursor ?? null} pending={groups.isFetching || search !== debounced} onChange={setCursor} />
    {selectedGroup && <GroupReuseDialog agencyId={agencyId} companyId={companyId} group={selectedGroup} onClose={() => setSelectedGroup(null)} />}
    {enrollmentGroup && <TravellerEnrollmentDialog agencyId={agencyId} companyId={companyId} group={enrollmentGroup} onClose={() => setEnrollmentGroup(null)} />}
    {matchingGroup && <CompanyMatchingDialog agencyId={agencyId} companyId={companyId} group={matchingGroup} onClose={() => setMatchingGroup(null)} />}
  </div>;
}

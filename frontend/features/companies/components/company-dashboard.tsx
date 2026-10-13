"use client";

import { useId, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { ArrowLeft, Building2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ROUTES } from "@/constants/routes";
import { useCompany, useCompanySummary } from "../hooks/use-companies";
import { useCompanyAgency } from "./company-agency-scope";
import { CompanyError, CompanyLoading } from "./company-feedback";
import { CompanyOverviewStats } from "./company-overview-stats";
import { CompanyGroups } from "./company-groups";

const TABS = [{ id: "groups", label: "Groups" }, { id: "settings", label: "Settings" }, { id: "data", label: "All data" }] as const;
const CompanySettings = dynamic(() => import("./company-settings").then((module) => module.CompanySettings), { loading: () => <CompanyLoading /> });
const CompanyAllData = dynamic(() => import("./company-all-data").then((module) => module.CompanyAllData), { loading: () => <CompanyLoading /> });

export function CompanyDashboard({ companyId }: { companyId: string }) {
  const agencyId = useCompanyAgency();
  const company = useCompany(agencyId, companyId);
  const summary = useCompanySummary(agencyId, companyId);
  const [tab, setTab] = useState<typeof TABS[number]["id"]>("groups");
  const tabId = useId();
  if (company.isLoading) return <CompanyLoading />;
  if (company.isError || !company.data) return <CompanyError message="This company is unavailable." retry={() => void company.refetch()} />;

  return <div className="min-w-0 space-y-5">
    <Link prefetch={false} href={ROUTES.dashboard.companies} className="inline-flex min-h-10 items-center gap-2 rounded text-sm font-medium text-slate-500 hover:text-slate-900 focus-visible:ring-2 focus-visible:ring-blue-600"><ArrowLeft className="h-4 w-4" aria-hidden="true" />Companies</Link>
    <header className="flex min-w-0 items-center justify-between gap-3">
      <div className="flex min-w-0 items-center gap-3"><span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-blue-100 bg-blue-50 text-blue-700"><Building2 className="h-5 w-5" aria-hidden="true" /></span><div className="min-w-0"><h1 className="break-words text-2xl font-semibold tracking-tight text-slate-950 sm:text-3xl">{company.data.name}</h1><p className="mt-1 text-xs text-slate-500">{company.data.status === "active" ? "Client company" : "Inactive company"}</p></div></div>
      <Button type="button" variant="ghost" size="icon" aria-label="Refresh company overview" disabled={company.isFetching || summary.isFetching} onClick={() => void Promise.all([company.refetch(), summary.refetch()])}><RefreshCw className={`h-4 w-4 ${company.isFetching || summary.isFetching ? "motion-safe:animate-spin" : ""}`} aria-hidden="true" /></Button>
    </header>
    {summary.isError ? <CompanyError message="Totals could not be loaded." retry={() => void summary.refetch()} /> : <CompanyOverviewStats loading={summary.isLoading} values={{ completedGroups: summary.data?.completed_groups ?? null, activeGroups: summary.data?.current_groups ?? null, passengerTrips: summary.data?.passenger_trips_completed ?? null, uniquePeople: summary.data?.unique_travellers ?? null }} />}
    {summary.data?.identity_totals_partial && !summary.isError && <p className="text-xs text-slate-500">Unique people are updating.</p>}
    <div className="flex gap-1 border-b border-slate-200" role="tablist" aria-label="Company views">
      {TABS.map((item, index) => <button key={item.id} type="button" role="tab" id={`${tabId}-${item.id}`} aria-controls={`${tabId}-panel`} aria-selected={tab === item.id} tabIndex={tab === item.id ? 0 : -1}
        onKeyDown={(event) => {
          let next: number;
          if (event.key === "ArrowLeft" || event.key === "ArrowRight") next = (index + (event.key === "ArrowRight" ? 1 : -1) + TABS.length) % TABS.length;
          else if (event.key === "Home") next = 0;
          else if (event.key === "End") next = TABS.length - 1;
          else return;
          event.preventDefault(); setTab(TABS[next].id); document.getElementById(`${tabId}-${TABS[next].id}`)?.focus();
        }} onClick={() => setTab(item.id)} className={`min-h-11 flex-1 border-b-2 px-3 py-3 text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 sm:flex-none sm:px-5 ${tab === item.id ? "border-blue-600 text-blue-700" : "border-transparent text-slate-500 hover:text-slate-900"}`}>{item.label}</button>)}
    </div>
    <section role="tabpanel" id={`${tabId}-panel`} aria-labelledby={`${tabId}-${tab}`} className="min-w-0">
      {tab === "groups" ? <CompanyGroups agencyId={agencyId} companyId={companyId} /> : tab === "settings" ? <CompanySettings agencyId={agencyId} companyId={companyId} active={company.data.status === "active"} /> : <CompanyAllData agencyId={agencyId} companyId={companyId} />}
    </section>
  </div>;
}

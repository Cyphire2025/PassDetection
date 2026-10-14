"use client";

import { useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Pencil, UserRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { companyPeopleApi } from "../api/company-people.api";
import { companyKeys, useCompanyQueryContext } from "../hooks/use-companies";
import { useCompanyViewState } from "../hooks/use-company-view-state";
import { companyPersonHref, companyViewHref } from "../utils/company-navigation";
import { useCompanyAgency } from "./company-agency-scope";
import { CompanyError, CompanyLoading } from "./company-feedback";
import { CompanyPersonEditor } from "./company-person-editor";
import { CompanyPersonDetails } from "./company-person-details";
import { CompanyViewTabs } from "./company-view-tabs";

const CompanyPersonDocuments = dynamic(() => import("./company-person-documents").then((module) => module.CompanyPersonDocuments), { loading: () => <CompanyLoading /> });
const CompanyPersonTrips = dynamic(() => import("./company-person-trips").then((module) => module.CompanyPersonTrips), { loading: () => <CompanyLoading /> });
const CompanyPassports = dynamic(() => import("./company-passports").then((module) => module.CompanyPassports), { loading: () => <CompanyLoading /> });
const TABS = [{ id: "documents", label: "Documents & submissions" }, { id: "record", label: "Current details" }, { id: "trips", label: "Trip groups" }] as const;

export function CompanyPersonPage({ companyId, personId }: { companyId: string; personId: string }) {
  const agencyId = useCompanyAgency();
  const { scope, ready } = useCompanyQueryContext(agencyId);
  const client = useQueryClient();
  const view = useCompanyViewState();
  const tab = TABS.find((item) => item.id === view.params.get("personTab"))?.id ?? "documents";
  const [managePassports, setManagePassports] = useState(false);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const record = useQuery({ queryKey: [...scope, companyId, "people", personId, "record"], queryFn: ({ signal }) => companyPeopleApi.record(agencyId, companyId, personId, signal), enabled: ready, staleTime: 0, gcTime: 0, refetchOnWindowFocus: false, retry: false });
  const onSaved = async () => { setEditing(false); setSaved(true); await client.invalidateQueries({ queryKey: companyKeys.scope(agencyId) }); };
  const data = ready && !record.isError ? record.data : undefined;
  const back = new URLSearchParams(view.query); back.delete("personTab"); back.set("tab", "data");
  return <div className="min-w-0 space-y-5">
    <Link prefetch={false} href={companyViewHref(companyId, back.toString())} className="inline-flex min-h-10 items-center gap-2 rounded text-sm font-medium text-slate-500 hover:text-slate-900 focus-visible:ring-2 focus-visible:ring-blue-600"><ArrowLeft className="h-4 w-4" aria-hidden="true" />Back to company</Link>
    <header className="flex min-w-0 flex-wrap items-center justify-between gap-3"><div className="flex min-w-0 items-center gap-3"><span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-slate-200 bg-white text-blue-900"><UserRound className="h-5 w-5" aria-hidden="true" /></span><div className="min-w-0"><h1 className="break-words text-2xl font-semibold tracking-tight text-slate-950">{editing ? "Edit current details" : data?.display_name ?? "Person details"}</h1><p className="mt-1 text-xs text-slate-500">Current details, submissions and trip groups</p></div></div>{data && !editing && <Button type="button" variant="secondary" disabled={busy} onClick={() => { setEditing(true); setSaved(false); }}><Pencil className="h-4 w-4" aria-hidden="true" />Edit details</Button>}</header>
    {!ready || record.isLoading ? <CompanyLoading /> : record.isError || !data ? <CompanyError message="This record could not be loaded." retry={() => void record.refetch()} /> : editing ? <section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-6"><CompanyPersonEditor agencyId={agencyId} companyId={companyId} record={data} onBusy={setBusy} onSaved={onSaved} onCancel={() => setEditing(false)} /></section> : <>
      {saved && <p role="status" className="text-sm text-emerald-700">Changes saved. Previous trips are unchanged.</p>}
      <CompanyViewTabs tabs={TABS} value={tab} onChange={(value) => view.update({ personTab: value })} label="Person views" disabled={busy} />
      <section role="tabpanel" aria-label={TABS.find((item) => item.id === tab)?.label}>
        {tab === "trips" ? <CompanyPersonTrips agencyId={agencyId} companyId={companyId} personId={personId} returnTo={companyPersonHref(companyId, personId, view.query)} /> : tab === "documents" ? <CompanyPersonDocuments agencyId={agencyId} companyId={companyId} record={data} onBusy={setBusy} onSaved={onSaved} /> : <CompanyPersonDetails record={data} />}
      </section>
      {tab === "documents" && data.current_document && <Button type="button" variant="ghost" onClick={() => setManagePassports(true)}>Manage passport status</Button>}
    </>}
    {managePassports && data && <CompanyPassports agencyId={agencyId} companyId={companyId} travellerId={personId} onClose={() => setManagePassports(false)} />}
  </div>;
}

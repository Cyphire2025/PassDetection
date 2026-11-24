"use client";

import dynamic from "next/dynamic";
import { Button } from "@/components/ui/button";
import type { useCompanyPersonPage } from "../hooks/use-company-person-page";
import { companyPersonHref } from "../utils/company-navigation";
import { CompanyError, CompanyLoading } from "./company-feedback";
import { CompanyPersonEditor } from "./company-person-editor";
import { CompanyPersonDetails } from "./company-person-details";
import { CompanyViewTabs } from "./company-view-tabs";

const CompanyPersonDocuments = dynamic(() => import("./company-person-documents").then((module) => module.CompanyPersonDocuments), { loading: () => <CompanyLoading /> });
const CompanyPersonTrips = dynamic(() => import("./company-person-trips").then((module) => module.CompanyPersonTrips), { loading: () => <CompanyLoading /> });
const TABS = [{ id: "documents", label: "Documents & submissions" }, { id: "record", label: "Current details" }, { id: "trips", label: "Trip groups" }] as const;

export function CompanyPersonContent({ companyId, personId, state }: {
  companyId: string;
  personId: string;
  state: ReturnType<typeof useCompanyPersonPage>;
}) {
  const { agencyId, ready, view, editing, setEditing, busy, setBusy, saved, record,
    onSaved, data, setManagePassports } = state;
  const tab = TABS.find((item) => item.id === view.params.get("personTab"))?.id ?? "documents";
  return <>
    {!ready || record.isLoading ? <CompanyLoading /> : record.isError || !data ? <CompanyError message="This record could not be loaded." retry={() => void record.refetch()} /> : editing ? <section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-6">
      <CompanyPersonEditor
        agencyId={agencyId}
        companyId={companyId}
        record={data}
        onBusy={setBusy}
        onSaved={onSaved}
        onCancel={() => setEditing(false)}
      />
    </section> : <>
      {saved && <p role="status" className="text-sm text-emerald-700">Changes saved. Previous trips are unchanged.</p>}
      <CompanyViewTabs
        tabs={TABS}
        value={tab}
        onChange={(value) => view.update({ personTab: value })}
        label="Person views"
        disabled={busy}
      />
      <section role="tabpanel" aria-label={TABS.find((item) => item.id === tab)?.label}>
        {tab === "trips" ? <CompanyPersonTrips
          agencyId={agencyId}
          companyId={companyId}
          personId={personId}
          returnTo={companyPersonHref(companyId, personId, view.query)}
        /> : tab === "documents" ? <CompanyPersonDocuments agencyId={agencyId} companyId={companyId} record={data} onBusy={setBusy} onSaved={onSaved} /> : <CompanyPersonDetails record={data} />}
      </section>
      {tab === "documents" && data.current_document && <Button type="button" variant="ghost" onClick={() => setManagePassports(true)}>Manage passport status</Button>}
    </>}
  </>;
}

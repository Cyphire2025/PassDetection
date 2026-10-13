"use client";

import { useId, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { REVIEW_FIELDS } from "@/features/upload/components/upload-flow.constants";
import { toLabel } from "@/features/upload/services/upload-flow-helpers";
import { formatPassportCountry } from "@/lib/utils/passport-country";
import { companyPeopleApi } from "../api/company-people.api";
import { companyKeys, useCompanyQueryContext } from "../hooks/use-companies";
import { CompanyError, CompanyLoading } from "./company-feedback";
import { CompanyPersonEditor } from "./company-person-editor";
import { CompanyOriginalRecord } from "./company-original-record";

const CompanyPersonDocuments = dynamic(() => import("./company-person-documents").then((module) => module.CompanyPersonDocuments), { loading: () => <CompanyLoading /> });
const CompanyPersonTrips = dynamic(() => import("./company-person-trips").then((module) => module.CompanyPersonTrips), { loading: () => <CompanyLoading /> });
const CompanyPassports = dynamic(() => import("./company-passports").then((module) => module.CompanyPassports), { loading: () => <CompanyLoading /> });

export function CompanyPersonDialog({ agencyId, companyId, personId, onClose }: { agencyId: string; companyId: string; personId: string; onClose: () => void }) {
  const { scope, ready } = useCompanyQueryContext(agencyId);
  const client = useQueryClient();
  const [tab, setTab] = useState<"record" | "documents" | "trips">("record");
  const [managePassports, setManagePassports] = useState(false);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const title = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const keyboard = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: !busy, onClose });
  const record = useQuery({ queryKey: [...scope, companyId, "people", personId, "record"], queryFn: ({ signal }) => companyPeopleApi.record(agencyId, companyId, personId, signal), enabled: ready, staleTime: 0, gcTime: 0, refetchOnWindowFocus: false, retry: false });
  const onSaved = async () => { setEditing(false); setSaved(true); await client.invalidateQueries({ queryKey: companyKeys.scope(agencyId) }); };
  const data = record.isError ? undefined : record.data;
  if (managePassports && ready && data) return <CompanyPassports agencyId={agencyId} companyId={companyId} travellerId={personId} onClose={() => setManagePassports(false)} />;
  return <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={title} onKeyDown={keyboard} className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-2 sm:p-5"><section className="flex max-h-[94dvh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-white shadow-xl">
    <header className="flex items-start justify-between gap-3 border-b border-slate-100 p-4 sm:px-6"><div className="min-w-0"><h2 id={title} className="break-words text-lg font-semibold text-slate-950">{editing ? "Edit current record" : data?.display_name ?? "Person record"}</h2><p className="mt-1 text-xs text-slate-500">Current details and saved document versions</p></div><Button type="button" size="icon" variant="ghost" aria-label="Close person record" disabled={busy} onClick={onClose}><X className="h-4 w-4" aria-hidden="true" /></Button></header>
    <div className="space-y-5 overflow-y-auto overscroll-contain p-4 sm:p-6">
      {!ready || record.isLoading ? <CompanyLoading /> : record.isError || !data ? <CompanyError message="This record could not be loaded." retry={() => void record.refetch()} /> : editing ? <CompanyPersonEditor agencyId={agencyId} companyId={companyId} record={data} onBusy={setBusy} onSaved={onSaved} onCancel={() => setEditing(false)} /> : <>
        {saved && <p role="status" className="text-sm text-emerald-700">Changes saved. Previous trips are unchanged.</p>}
        <div className="flex flex-wrap gap-2"><Button type="button" disabled={busy} variant={tab === "record" ? "primary" : "secondary"} onClick={() => setTab("record")}>Details</Button><Button type="button" disabled={busy} variant={tab === "documents" ? "primary" : "secondary"} onClick={() => setTab("documents")}>Documents</Button><Button type="button" disabled={busy} variant={tab === "trips" ? "primary" : "secondary"} onClick={() => setTab("trips")}>Trip history</Button>{tab === "record" && <Button type="button" variant="ghost" className="ml-auto" onClick={() => { setEditing(true); setSaved(false); }}><Pencil className="h-4 w-4" aria-hidden="true" />Edit details</Button>}</div>
        {tab === "trips" ? <CompanyPersonTrips agencyId={agencyId} companyId={companyId} personId={personId} /> : tab === "documents" ? <CompanyPersonDocuments agencyId={agencyId} companyId={companyId} record={data} onBusy={setBusy} onSaved={onSaved} /> : <>
          <dl className="grid gap-4 sm:grid-cols-2"><Detail label="Full name" value={data.display_name} /><Detail label="Contact number" value={data.phone_number ? `${data.phone_number}${data.phone_verified ? " · Verified" : " · Unverified"}` : null} />{data.current_document && <><Detail label="Issuing country" value={formatPassportCountry(data.current_document.issuing_country)} /><Detail label="Document type" value={data.current_document.document_type} />{REVIEW_FIELDS.map((field) => <Detail key={field} label={toLabel(field)} value={data.current_document?.fields[field]} />)}</>}</dl>
          {!data.current_document && <p className="text-sm text-slate-500">No current passport has been saved.</p>}
          {!data.current_document && data.original_record && <CompanyOriginalRecord record={data.original_record} />}
          {data.current_document && <Button type="button" variant="secondary" onClick={() => setManagePassports(true)}>Manage passport status</Button>}
        </>}
      </>}
    </div>
  </section></div>;
}

function Detail({ label, value }: { label: string; value?: string | null }) {
  return <div className="min-w-0"><dt className="text-xs font-medium text-slate-500">{label}</dt><dd className="mt-1 break-words text-sm text-slate-950">{value || "—"}</dd></div>;
}

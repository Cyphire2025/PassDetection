"use client";

import { useState } from "react";
import { CompanyLogo } from "@/features/branding/components/company-logo";
import Link from "next/link";
import { ArrowRight, Building2, Pencil, Plus, RefreshCw } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/modal";
import { WorkspaceEmptyState, WorkspacePageHeader, WorkspaceToolbar } from "@/components/shared/workspace-ui";
import { ROUTES } from "@/constants/routes";
import { useDebounce } from "@/hooks/use-debounce";
import { useCompanies, useCompanyMutations } from "../hooks/use-companies";
import type { Company, CompanySearch } from "../types";
import { useCompanyAgency } from "./company-agency-scope";
import { CompanyForm } from "./company-form";
import { CompanyError, CompanyLoading, CompanyPagination, companyErrorMessage } from "./company-feedback";

export function CompanyDirectory() {
  const agencyId = useCompanyAgency();
  const [search, setSearch] = useState("");
  const debounced = useDebounce(search, 250);
  const [status, setStatus] = useState<CompanySearch["status"]>("all");
  const [cursor, setCursor] = useState<string>();
  const [editor, setEditor] = useState<{ company: Company | null } | null>(null);
  const [action, setAction] = useState<{ company: Company; type: "status" | "delete" } | null>(null);
  const [error, setError] = useState<string>();
  const companies = useCompanies(agencyId, { search: debounced, status, cursor, page_size: 25 });
  const mutations = useCompanyMutations(agencyId);
  const pending = mutations.update.isPending || mutations.remove.isPending;

  const confirm = async () => {
    if (!action || pending) return;
    setError(undefined);
    try {
      if (action.type === "delete") await mutations.remove.mutateAsync(action.company);
      else await mutations.update.mutateAsync({ id: action.company.id, expected_revision: action.company.revision, status: action.company.status === "active" ? "inactive" : "active" });
      setAction(null);
    } catch (cause) { setError(companyErrorMessage(cause, "This company could not be updated. Refresh and try again.")); setAction(null); }
  };

  return <div className="space-y-5">
    <WorkspacePageHeader title="Companies / Clients" description="Your clients, groups and passengers." className="pb-0" icon={Building2} actions={<Button className="min-h-10" onClick={() => setEditor({ company: null })}><Plus className="h-4 w-4" aria-hidden="true" />Add client company</Button>} />
    {error && <CompanyError message={error} />}
    <section aria-label="Company directory" className="min-w-0 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <WorkspaceToolbar query={search} onQueryChange={(value) => { setSearch(value); setCursor(undefined); }} searchLabel="Search company directory" placeholder="Search companies by name">
        <label className="flex items-center gap-2 text-sm text-slate-600">Status<select aria-label="Company status" value={status} onChange={(event) => { setStatus(event.target.value as CompanySearch["status"]); setCursor(undefined); }} className="min-h-10 rounded-lg border border-slate-300 bg-white px-3 focus-visible:ring-2 focus-visible:ring-blue-600"><option value="all">All companies</option><option value="active">Active</option><option value="inactive">Inactive</option></select></label>
        <Button type="button" variant="ghost" size="icon" aria-label="Refresh companies" disabled={companies.isFetching} onClick={() => void companies.refetch()}><RefreshCw className={`h-4 w-4 ${companies.isFetching ? "motion-safe:animate-spin" : ""}`} aria-hidden="true" /></Button>
      </WorkspaceToolbar>
      {companies.isLoading || search !== debounced ? <CompanyLoading /> : companies.isError ? <CompanyError message="The company directory could not be loaded." retry={() => void companies.refetch()} /> : companies.data?.items.length ? <ul className="divide-y divide-slate-100">
        {companies.data.items.map((company) => <li key={company.id} className="flex flex-col gap-3 px-4 py-4 transition-colors hover:bg-slate-50/50 sm:flex-row sm:items-center sm:justify-between sm:px-5">
          <div className="flex min-w-0 items-start gap-3">
            <CompanyLogo src={company.logo_url} name={company.name} />
            <div className="min-w-0"><Link prefetch={false} href={ROUTES.dashboard.company(company.id)} className="break-words rounded text-sm font-semibold text-slate-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600">{company.name}</Link>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-xs"><span className={`inline-flex items-center gap-1.5 ${company.status === "active" ? "text-emerald-700" : "text-slate-500"}`}><span className={`h-1.5 w-1.5 rounded-full ${company.status === "active" ? "bg-emerald-500" : "bg-slate-400"}`} aria-hidden="true" />{company.status === "active" ? "Active" : "Inactive"}</span>{company.external_reference && <span className="break-all text-slate-400">{company.external_reference}</span>}</div>
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 sm:justify-end">
            <div className="flex flex-wrap items-center gap-0.5"><Button type="button" size="sm" variant="ghost" className="min-h-10" onClick={() => setEditor({ company })} aria-label={`Edit ${company.name}`}><Pencil className="h-3.5 w-3.5" aria-hidden="true" />Edit</Button><Button type="button" size="sm" variant="ghost" className="min-h-10" onClick={() => setAction({ company, type: "status" })}>{company.status === "active" ? "Deactivate" : "Reactivate"}</Button><Button type="button" size="sm" variant="ghost" className="min-h-10 text-red-700 hover:text-red-800" onClick={() => setAction({ company, type: "delete" })} aria-label={`Remove ${company.name}`}>Remove</Button></div>
            <Link prefetch={false} href={ROUTES.dashboard.company(company.id)} aria-label={`View company: ${company.name}`} className={buttonVariants({ variant: "secondary", size: "sm", className: "min-h-10 border-blue-200 text-blue-700 hover:bg-blue-50" })}>View company<ArrowRight className="h-3.5 w-3.5" aria-hidden="true" /></Link>
          </div>
        </li>)}
      </ul> : <WorkspaceEmptyState title={search ? "No matching companies" : "No companies in this view"} description={search ? "Try a different name or status filter." : "Add your first client company to get started."} />}
      <CompanyPagination cursor={cursor} hasMore={companies.data?.has_more ?? false} nextCursor={companies.data?.next_cursor ?? null} pending={companies.isFetching || search !== debounced} onChange={setCursor} />
    </section>
    {editor && <CompanyForm agencyId={agencyId} company={editor.company} onClose={() => setEditor(null)} />}
    <ConfirmDialog isOpen={Boolean(action)} title={action?.type === "delete" ? "Remove company?" : action?.company.status === "active" ? "Deactivate company?" : "Reactivate company?"} description={action?.type === "delete" ? "Groups will become unassigned. Passenger records and document history are kept." : action?.company.status === "active" ? "Stop new groups and saved-document reuse. Existing records stay available." : "This company will be available for new assignments again."} confirmLabel={action?.type === "delete" ? "Remove company" : "Confirm status change"} variant={action?.type === "delete" ? "danger" : "primary"} isLoading={pending} onClose={() => setAction(null)} onConfirm={() => void confirm()} />
  </div>;
}

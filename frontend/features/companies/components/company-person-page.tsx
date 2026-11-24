"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { ArrowLeft } from "lucide-react";
import { companyViewHref } from "../utils/company-navigation";
import { CompanyLoading } from "./company-feedback";
import { CompanyPersonHeader } from "./company-person-header";
import { CompanyPersonContent } from "./company-person-content";
import { useCompanyPersonPage } from "../hooks/use-company-person-page";

const CompanyPassports = dynamic(() => import("./company-passports").then((module) => module.CompanyPassports), { loading: () => <CompanyLoading /> });

export function CompanyPersonPage({ companyId, personId }: {
  companyId: string;
  personId: string
}) {
  const state = useCompanyPersonPage(companyId, personId);
  const { agencyId, managePassports, setManagePassports, editing, setEditing,
    busy, setSaved, data, back } = state;
  return <div className="min-w-0 space-y-5">
    <Link
      prefetch={false}
      href={companyViewHref(companyId, back.toString())}
      className="inline-flex min-h-10 items-center gap-2 rounded text-sm font-medium text-slate-500 hover:text-slate-900 focus-visible:ring-2 focus-visible:ring-blue-600"
    ><ArrowLeft className="h-4 w-4" aria-hidden="true" />Back to company</Link>
    <CompanyPersonHeader
      data={data}
      editing={editing}
      busy={busy}
      onEdit={() => {
        setEditing(true);
        setSaved(false);
      }}
    />
    <CompanyPersonContent companyId={companyId} personId={personId} state={state} />
    {managePassports && data && <CompanyPassports
      agencyId={agencyId}
      companyId={companyId}
      travellerId={personId}
      onClose={() => setManagePassports(false)}
    />}
  </div>;
}

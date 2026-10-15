"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { companyPeopleApi } from "../api/company-people.api";
import { companyQueryOptions, useCompanyQueryContext } from "../hooks/use-companies";
import { CompanyError, CompanyLoading, CompanyPagination } from "./company-feedback";
import { CompanyDocumentPreview } from "./company-document-preview";

export function CompanyOriginalDocuments({ agencyId, companyId, personId }: { agencyId: string; companyId: string; personId: string }) {
  const { scope, ready } = useCompanyQueryContext(agencyId);
  const [cursor, setCursor] = useState<string>();
  const sources = useQuery({ queryKey: [...scope, companyId, "people", personId, "sources", cursor], queryFn: ({ signal }) => companyPeopleApi.sources(agencyId, companyId, personId, cursor, signal), enabled: ready, ...companyQueryOptions });
  return <section className="space-y-4" aria-label="All submissions"><header><h2 className="text-base font-semibold text-slate-950">All submissions</h2><p className="mt-1 text-sm text-slate-500">Latest first. Earlier submissions and their original documents are preserved.</p></header>
    {!ready || sources.isLoading ? <CompanyLoading /> : sources.isError ? <CompanyError message="Submissions could not be loaded." retry={() => void sources.refetch()} /> : <>
      <ol className="space-y-5">{sources.data?.items.map((source, index) => <li key={source.id} className="space-y-4 rounded-2xl border border-slate-200 bg-white p-4 sm:p-5"><header className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="break-words text-sm font-semibold text-slate-900">{source.group_name}</h3><p className="mt-1 text-xs text-slate-500">{new Date(source.created_at).toLocaleString()} · Revision {source.revision_number}</p></div>{!cursor && index === 0 && <span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700">Latest submission</span>}</header>
        <div className="grid gap-4 lg:grid-cols-2">{source.available_sides.map((side) => <CompanyDocumentPreview key={`${source.id}:${side}`} agencyId={agencyId} companyId={companyId} personId={personId} document={{ kind: "source", sourceId: source.id, side }} />)}</div>
        {!source.available_sides.length && <p className="text-sm text-slate-500">No available images.</p>}
        <Link prefetch={false} href={`/passports/${encodeURIComponent(source.id)}`} className="inline-flex min-h-10 items-center text-sm font-medium text-blue-700 hover:text-blue-900">View complete submission</Link>
      </li>)}</ol>
      {!sources.data?.items.length && <p className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-500">No original submissions are available in this view.</p>}
      {Boolean(cursor || sources.data?.has_more) && <CompanyPagination cursor={cursor} hasMore={sources.data?.has_more ?? false} nextCursor={sources.data?.next_cursor ?? null} pending={sources.isFetching} onChange={setCursor} />}
    </>}
  </section>;
}

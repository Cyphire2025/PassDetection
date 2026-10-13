"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { WorkspaceEmptyState, WorkspaceToolbar } from "@/components/shared/workspace-ui";
import { PASSPORT_STATUS_LABELS } from "@/constants";
import { ROUTES } from "@/constants/routes";
import { useDebounce } from "@/hooks/use-debounce";
import { companiesApi } from "../api/companies.api";
import { companyKeys } from "../hooks/use-companies";
import { CompanyError, CompanyLoading, CompanyPagination } from "./company-feedback";

/** Loads only the current 25-record page; documents are opened on their own detail route. */
export function CompanyCollectedRecords({ agencyId, companyId }: { agencyId: string; companyId: string }) {
  const [search, setSearch] = useState("");
  const [cursor, setCursor] = useState<string>();
  const term = search.trim();
  const debounced = useDebounce(term, 250);
  const validSearch = !term || term.length >= 3;
  const settled = term === debounced;
  const result = useQuery({
    queryKey: [...companyKeys.scope(agencyId), companyId, "submissions", debounced, cursor],
    queryFn: ({ signal }) => companiesApi.submissions(agencyId, companyId, { search: debounced, cursor }, signal),
    enabled: settled && validSearch,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  });

  return <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
    <WorkspaceToolbar query={search} onQueryChange={(value) => { setSearch(value); setCursor(undefined); }} searchLabel="Search collected records" placeholder="Search names (at least 3 characters)" />
    <p className="border-b border-slate-100 px-4 py-3 text-xs leading-5 text-slate-500">Submissions from all assigned groups you can view, including records not yet linked to a retained traveller. One person can have several records; this is not a count of unique people.</p>
    {!validSearch ? <p role="status" className="p-4 text-sm text-slate-600">Enter at least 3 characters to search names, or clear the search to see all records.</p>
      : !settled || result.isLoading ? <CompanyLoading />
      : result.isError ? <CompanyError message="Collected records could not be loaded. Retry, or return to the first page if these results have changed." retry={() => void result.refetch()} />
      : result.data?.items.length ? <ul className="divide-y divide-slate-100">
        {result.data.items.map((record) => <li key={record.id} className="flex min-w-0 flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
          <div className="min-w-0 space-y-1.5">
            <Link prefetch={false} href={ROUTES.dashboard.passportDetail(record.id)} className="break-words text-sm font-semibold text-blue-800 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600">{record.display_name}</Link>
            <p className="text-xs text-slate-600"><Link prefetch={false} href={ROUTES.dashboard.passportGroup(record.group_id)} className="break-words text-blue-800 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600">{record.group_name}</Link><span> · {record.travel_date ?? "Travel date not set"}</span></p>
          </div>
          <span className="w-fit shrink-0 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700">{PASSPORT_STATUS_LABELS[record.status] ?? record.status.replaceAll("_", " ")}</span>
        </li>)}
      </ul> : <WorkspaceEmptyState title="No collected records in this view" description={term ? "Try a different name or clear the search." : "Records appear here when submissions are collected in groups assigned to this client company."} />}
    <CompanyPagination cursor={cursor} hasMore={result.data?.has_more ?? false} nextCursor={result.data?.next_cursor ?? null} pending={result.isFetching || !settled || !validSearch} onChange={setCursor} />
  </div>;
}

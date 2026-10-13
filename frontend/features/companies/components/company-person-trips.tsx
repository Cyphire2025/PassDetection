"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ROUTES } from "@/constants/routes";
import { companiesApi } from "../api/companies.api";
import { useCompanyQueryContext } from "../hooks/use-companies";
import { CompanyError, CompanyLoading, CompanyPagination } from "./company-feedback";

export function CompanyPersonTrips({ agencyId, companyId, personId }: { agencyId: string; companyId: string; personId: string }) {
  const { scope, ready } = useCompanyQueryContext(agencyId);
  const [cursor, setCursor] = useState<string>();
  const result = useQuery({
    queryKey: [...scope, companyId, "people", personId, "history", cursor],
    queryFn: ({ signal }) => companiesApi.history(agencyId, companyId, personId, cursor, signal),
    enabled: ready, staleTime: 0, gcTime: 0, retry: false, refetchOnWindowFocus: false,
  });
  if (!ready || result.isLoading) return <CompanyLoading />;
  if (result.isError) return <CompanyError message="Trip history could not be loaded." retry={() => void result.refetch()} />;
  return <div className="overflow-hidden rounded-xl border border-slate-200">
    <ul className="divide-y divide-slate-100">{result.data?.items.map((trip) => <li key={trip.id} className="p-4">
      <Link prefetch={false} href={ROUTES.dashboard.passportGroup(trip.group_id)} className="break-words text-sm font-semibold text-blue-800 hover:underline">{trip.group_name}</Link>
      <p className="mt-1 text-xs text-slate-500">{trip.travel_date ?? "Date not set"} · {trip.participation_status.replaceAll("_", " ")}</p>
    </li>)}</ul>
    {!result.data?.items.length && <p className="p-4 text-sm text-slate-500">No saved trip history yet.</p>}
    {Boolean(cursor || result.data?.next_cursor) && <CompanyPagination cursor={cursor} hasMore={Boolean(result.data?.next_cursor)} nextCursor={result.data?.next_cursor ?? null} pending={result.isFetching} onChange={setCursor} />}
  </div>;
}

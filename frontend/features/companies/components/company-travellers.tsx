"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { ChevronDown } from "lucide-react";
import { WorkspaceEmptyState, WorkspaceToolbar } from "@/components/shared/workspace-ui";
import { Button } from "@/components/ui/button";
import { useDebounce } from "@/hooks/use-debounce";
import { ROUTES } from "@/constants/routes";
import { companiesApi } from "../api/companies.api";
import { companyKeys } from "../hooks/use-companies";
import { CompanyError, CompanyLoading, CompanyPagination } from "./company-feedback";
import { CompanyPassports } from "./company-passports";

export function CompanyTravellers({ agencyId, companyId }: { agencyId: string; companyId: string }) {
  const [search, setSearch] = useState("");
  const debounced = useDebounce(search, 250);
  const [cursor, setCursor] = useState<string>();
  const [expanded, setExpanded] = useState<string | null>(null);
  const result = useQuery({
    queryKey: [...companyKeys.scope(agencyId), companyId, "travellers", debounced, cursor],
    queryFn: ({ signal }) => companiesApi.travellers(agencyId, companyId, { search: debounced, cursor }, signal),
    staleTime: 0, gcTime: 0, retry: 1,
  });
  return <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
    <WorkspaceToolbar query={search} onQueryChange={(value) => { setSearch(value); setCursor(undefined); setExpanded(null); }} searchLabel="Search company travellers by full name" placeholder="Search full name" />
    <p className="border-b border-slate-100 px-4 py-3 text-xs leading-5 text-slate-500">Search by full name (ignoring capitalisation and extra spaces). Open a resolved traveller to load visible trip history. Passport files remain separately protected.</p>
    {result.isLoading || search !== debounced ? <CompanyLoading /> : result.isError ? <CompanyError message="Traveller history could not be loaded. Please retry or contact your administrator." retry={() => void result.refetch()} /> : result.data?.items.length ? <ul className="divide-y divide-slate-100">
      {result.data.items.map((traveller) => <li key={traveller.id} className="p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3"><div className="min-w-0"><p className="break-words text-sm font-semibold text-slate-900">{traveller.display_name}</p><p className="mt-1 text-xs text-slate-500">{traveller.participation_count.toLocaleString()} trip participations · Latest trip: {traveller.last_trip_date ?? "Date not set"}</p></div><Button type="button" size="sm" variant="secondary" aria-expanded={expanded === traveller.id} aria-controls={`history-${traveller.id}`} onClick={() => setExpanded(expanded === traveller.id ? null : traveller.id)}>{expanded === traveller.id ? "Close history" : "View history"}<ChevronDown className="h-3.5 w-3.5" aria-hidden="true" /></Button></div>
        {expanded === traveller.id && <div id={`history-${traveller.id}`} className="mt-4"><TravellerTrips agencyId={agencyId} companyId={companyId} travellerId={traveller.id} /></div>}
      </li>)}
    </ul> : <WorkspaceEmptyState title="No resolved travellers in this view" description="Historical records appear here after authorised reconciliation establishes their identity and trip participation." />}
    <CompanyPagination cursor={cursor} hasMore={Boolean(result.data?.next_cursor)} nextCursor={result.data?.next_cursor ?? null} pending={result.isFetching || search !== debounced} onChange={(next) => { setCursor(next); setExpanded(null); }} />
  </div>;
}

function TravellerTrips({ agencyId, companyId, travellerId }: { agencyId: string; companyId: string; travellerId: string }) {
  const [cursor, setCursor] = useState<string>();
  const [managePassports, setManagePassports] = useState(false);
  const result = useQuery({
    queryKey: [...companyKeys.scope(agencyId), companyId, "travellers", travellerId, "history", cursor],
    queryFn: ({ signal }) => companiesApi.history(agencyId, companyId, travellerId, cursor, signal),
    staleTime: 0, gcTime: 0, retry: 1,
  });
  if (result.isLoading) return <CompanyLoading />;
  if (result.isError) return <CompanyError message="This traveller's history could not be loaded." retry={() => void result.refetch()} />;
  return <div className="overflow-hidden rounded-xl border border-slate-200 bg-slate-50">
    <div className="border-b border-slate-200 p-3"><Button type="button" variant="secondary" className="min-h-11" onClick={() => setManagePassports(true)}>Manage passports</Button></div>
    <ul className="divide-y divide-slate-200">{result.data?.items.map((trip) => <li key={trip.id} className="p-3 text-xs leading-5"><Link href={ROUTES.dashboard.passportGroup(trip.group_id)} className="break-words text-sm font-semibold text-blue-800 hover:underline">{trip.group_name}</Link><p className="text-slate-600">{trip.travel_date ?? "Date not set"} · {trip.lifecycle} · {trip.participation_status}</p><p className="text-slate-500">Document revision used: {trip.document_revision ?? "Not recorded"}</p></li>)}</ul>
    {!result.data?.items.length && <p className="p-4 text-sm text-slate-500">No visible history records.</p>}
    <CompanyPagination cursor={cursor} hasMore={Boolean(result.data?.next_cursor)} nextCursor={result.data?.next_cursor ?? null} pending={result.isFetching} onChange={setCursor} />
    {managePassports && <CompanyPassports agencyId={agencyId} companyId={companyId} travellerId={travellerId} onClose={() => setManagePassports(false)} />}
  </div>;
}

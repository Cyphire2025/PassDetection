"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import { useDebounce } from "@/hooks/use-debounce";
import { searchCompanyAgencies } from "../api/company-agency.api";

const AgencyContext = createContext<string | null>(null);

export function CompanyAgencySelector({ value, onChange }: { value: string | null; onChange: (agencyId: string) => void }) {
  const [search, setSearch] = useState("");
  const debounced = useDebounce(search, 250);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<{ id: string; name: string } | null>(null);
  const agencies = useQuery({ queryKey: ["companies", "agency-scope", debounced, offset], queryFn: ({ signal }) => searchCompanyAgencies(debounced, offset, signal), staleTime: 0, gcTime: 0, retry: 1 });
  const items = agencies.data?.items ?? [];
  const pending = agencies.isFetching || search !== debounced;
  return <div className="space-y-2 rounded-xl border border-slate-200 bg-white p-4">
    <Input label="Search agency workspaces" value={search} maxLength={120} onChange={(event) => { setSearch(event.target.value); setOffset(0); }} />
    <label className="block space-y-1.5 text-sm font-medium text-slate-700">Agency workspace<select value={value ?? ""} onChange={(event) => { const agency = items.find((item) => item.id === event.target.value); if (agency) { setSelected(agency); onChange(agency.id); } }} disabled={pending} className="min-h-11 w-full rounded-xl border border-slate-300 bg-white px-3"><option value="">Choose an agency workspace</option>{selected?.id === value && !items.some((agency) => agency.id === value) && <option value={selected.id}>{selected.name}</option>}{items.map((agency) => <option key={agency.id} value={agency.id}>{agency.name}</option>)}</select></label>
    <p className="text-xs text-slate-500">Select the agency whose companies you want to manage. {pending ? "Loading workspaces…" : !items.length ? "No matching workspaces." : ""}</p>
    <div className="flex flex-wrap gap-2"><Button type="button" size="sm" variant="secondary" disabled={pending || offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous agencies</Button><Button type="button" size="sm" variant="secondary" disabled={pending || offset + items.length >= (agencies.data?.total ?? 0)} onClick={() => setOffset(offset + 25)}>More agencies</Button></div>
    {agencies.isError && <div role="alert" className="text-sm text-red-700">Agency workspaces could not be loaded. <Button variant="secondary" size="sm" onClick={() => void agencies.refetch()}>Retry</Button></div>}
  </div>;
}

export function CompanyAgencyScope({ children }: { children: ReactNode }) {
  const user = useAuthStore(selectUser);
  const [selected, setSelected] = useState<string | null>(null);
  const agencyId = user?.role === "super_admin" ? selected : user?.agency_id ?? null;
  return <>
    {user?.role === "super_admin" && <CompanyAgencySelector value={selected} onChange={setSelected} />}
    {agencyId ? <AgencyContext.Provider key={agencyId} value={agencyId}>{children}</AgencyContext.Provider> : <p role="status" className="rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">Select an agency workspace to continue.</p>}
  </>;
}

export function useCompanyAgency() {
  const agency = useContext(AgencyContext);
  if (!agency) throw new Error("A company agency scope is required.");
  return agency;
}

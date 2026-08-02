"use client";

import { useQuery } from "@tanstack/react-query";
import { Fragment, createContext, useContext, useMemo, useState, type ReactNode } from "react";
import type { User } from "@/types";
import { gcAppAdminApi } from "../api/gc-app-admin.api";
import { GcAlert } from "./gc-app-feedback";

interface GcAppAgencyScopeValue {
  agencyId: string | null;
  isReady: boolean;
}

const GcAppAgencyScopeContext = createContext<GcAppAgencyScopeValue | null>(null);

export function GcAppAgencyScopeProvider({
  user,
  children,
}: {
  user: User;
  children: ReactNode;
}) {
  const isSuperAdmin = user.role === "super_admin";
  const [requestedAgencyId, setRequestedAgencyId] = useState<string | null>(null);
  const agencies = useQuery({
    queryKey: ["gc-app", "agency-scope"],
    queryFn: ({ signal }) => gcAppAdminApi.listAgencies(signal),
    enabled: isSuperAdmin,
    staleTime: 60_000,
    retry: 1,
  });

  const selectedAgencyId = isSuperAdmin
    ? (
      agencies.data?.some((agency) => agency.id === requestedAgencyId)
        ? requestedAgencyId
        : agencies.data?.[0]?.id ?? null
    )
    : user.agency_id;

  const selectAgency = (agencyId: string) => {
    if (!agencies.data?.some((agency) => agency.id === agencyId)) return;
    setRequestedAgencyId(agencyId);
  };

  const isReady = isSuperAdmin
    ? agencies.isSuccess && selectedAgencyId !== null
    : user.agency_id !== null;
  const value = useMemo(
    () => ({ agencyId: selectedAgencyId, isReady }),
    [isReady, selectedAgencyId],
  );

  return (
    <GcAppAgencyScopeContext.Provider value={value}>
      {isSuperAdmin ? (
        <div className="mb-5 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <label htmlFor="gc-app-agency-scope" className="mb-1.5 block text-sm font-medium text-slate-700">
            Agency workspace
          </label>
          {agencies.isError ? (
            <GcAlert message="Agency workspaces could not be loaded. Refresh before making GC App changes." />
          ) : (
            <select
              id="gc-app-agency-scope"
              value={selectedAgencyId ?? ""}
              disabled={!agencies.isSuccess}
              onChange={(event) => selectAgency(event.target.value)}
              className="h-10 w-full max-w-md rounded-lg border border-slate-300 bg-white px-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600 disabled:opacity-60"
            >
              <option value="" disabled>{agencies.isLoading ? "Loading agencies…" : "Select an agency"}</option>
              {agencies.data?.map((agency) => (
                <option key={agency.id} value={agency.id}>{agency.name}</option>
              ))}
            </select>
          )}
        </div>
      ) : null}
      {isReady ? <Fragment key={selectedAgencyId}>{children}</Fragment> : null}
    </GcAppAgencyScopeContext.Provider>
  );
}

export function useGcAppAgencyScope(): GcAppAgencyScopeValue {
  const value = useContext(GcAppAgencyScopeContext);
  if (!value) throw new Error("GC App agency scope is unavailable.");
  return value;
}

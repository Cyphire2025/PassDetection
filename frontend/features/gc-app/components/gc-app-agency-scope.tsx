"use client";

import { useQuery } from "@tanstack/react-query";
import { Fragment, createContext, useContext, useMemo, useState, type ReactNode } from "react";
import type { User } from "@/types";
import { gcAppAdminApi } from "../api/gc-app-admin.api";
import { GcAlert } from "./gc-app-feedback";
import { GcSelect } from "./gc-select";

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
    staleTime: 5 * 60_000,
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
        <div className="mb-5 rounded-2xl border border-slate-200 bg-gradient-to-r from-slate-50 to-white p-4 shadow-[0_8px_30px_-24px_rgba(15,23,42,0.4)]">
          {agencies.isError ? (
            <GcAlert message="Agency workspaces could not be loaded. Refresh before making GC App changes." />
          ) : (
            <GcSelect
              id="gc-app-agency-scope"
              label="Agency workspace"
              value={selectedAgencyId ?? ""}
              disabled={!agencies.isSuccess}
              onChange={selectAgency}
              options={(agencies.data ?? []).map((agency) => ({
                value: agency.id,
                label: agency.name,
                description: agency.email,
              }))}
              searchable
              loading={agencies.isLoading}
              placeholder="Select an agency"
              searchPlaceholder="Find agency workspace"
              className="max-w-md"
            />
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

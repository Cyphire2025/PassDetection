"use client";

import { useQuery } from "@tanstack/react-query";
import { companiesApi } from "../api/companies.api";
import { useCompanySession } from "./use-company-session";

/** Never retain a resolved workspace across account or access-level changes. */
export function useCompanyWorkspace(enabled = true) {
  const session = useCompanySession();
  const sessionKey = session.key;
  const active = enabled && session.ready;
  const query = useQuery({
    queryKey: ["company-workspace", sessionKey],
    queryFn: ({ signal }) => companiesApi.workspace(signal),
    enabled: active,
    staleTime: 5 * 60_000,
    gcTime: 5 * 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  });
  return { ...query, sessionKey, agencyId: active && !query.isError ? query.data?.agency_id ?? null : null };
}

export type CompanyWorkspace = ReturnType<typeof useCompanyWorkspace>;

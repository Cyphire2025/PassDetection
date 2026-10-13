"use client";

import { useQuery } from "@tanstack/react-query";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import { companiesApi } from "../api/companies.api";

/** Never retain a resolved workspace across account or access-level changes. */
export function useCompanyWorkspace(enabled = true) {
  const user = useAuthStore(selectUser);
  const sessionVersion = useAuthStore((state) => state.sessionVersion);
  const changingAccess = useAuthStore((state) => state.isChangingAccessLevel);
  const sessionKey = JSON.stringify([user?.id, user?.role, user?.agency_id, sessionVersion]);
  const active = enabled && Boolean(user) && !changingAccess;
  const query = useQuery({
    queryKey: ["company-workspace", sessionKey],
    queryFn: ({ signal }) => companiesApi.workspace(signal),
    enabled: active,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  });
  return { ...query, sessionKey, agencyId: active && !query.isError ? query.data?.agency_id ?? null : null };
}

export type CompanyWorkspace = ReturnType<typeof useCompanyWorkspace>;

"use client";

import { useMemo } from "react";
import { useCompanySession } from "./use-company-session";

/** Short, auth-scoped reuse avoids refocus flicker; mutations invalidate the agency prefix. */
export const companyQueryOptions = { staleTime: 60_000, gcTime: 5 * 60_000, refetchOnWindowFocus: false, retry: false } as const;

export const companyKeys = {
  scope: (agencyId: string | null) => ["companies", agencyId] as const,
};

export function useCompanyQueryScope(agencyId: string | null) {
  return useCompanyQueryContext(agencyId).scope;
}

export function useCompanyQueryContext(agencyId: string | null) {
  const session = useCompanySession();
  const scope = useMemo(
    () => [...companyKeys.scope(agencyId), "session", session.key, session.ready ? "ready" : "inactive"] as const,
    [agencyId, session.key, session.ready],
  );
  return {
    scope,
    ready: Boolean(agencyId) && session.ready,
  };
}

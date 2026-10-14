"use client";

import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { companiesApi } from "../api/companies.api";
import type { Company, CompanyGroupSearch, CompanyInput, CompanySearch, CompanyUpdate } from "../types";
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
  const scope = useMemo(() => [...companyKeys.scope(agencyId), "session", session.key,
    session.ready ? "ready" : "inactive"] as const, [agencyId, session.key, session.ready]);
  return {
    scope,
    ready: Boolean(agencyId) && session.ready,
  };
}

export function useCompanies(agencyId: string | null, params: CompanySearch) {
  const { scope, ready } = useCompanyQueryContext(agencyId);
  return useQuery({
    queryKey: [...scope, "directory", params],
    queryFn: ({ signal }) => companiesApi.list(agencyId!, params, signal),
    enabled: ready,
    ...companyQueryOptions,
  });
}

export function useCompanyLookup(agencyId: string | null, params: CompanySearch, enabled = true) {
  const { scope, ready } = useCompanyQueryContext(agencyId);
  return useQuery({
    queryKey: [...scope, "lookup", params],
    queryFn: ({ signal }) => companiesApi.lookup(agencyId!, params, signal),
    enabled: ready && enabled,
    ...companyQueryOptions,
  });
}

export function useCompany(agencyId: string | null, id: string) {
  const { scope, ready } = useCompanyQueryContext(agencyId);
  return useQuery({ queryKey: [...scope, id], queryFn: ({ signal }) => companiesApi.get(agencyId!, id, signal), enabled: ready, ...companyQueryOptions });
}

export function useCompanySummary(agencyId: string | null, id: string) {
  const { scope, ready } = useCompanyQueryContext(agencyId);
  return useQuery({ queryKey: [...scope, id, "summary"], queryFn: ({ signal }) => companiesApi.summary(agencyId!, id, signal), enabled: ready, ...companyQueryOptions });
}

export function useCompanyGroups(agencyId: string | null, id: string, params: CompanyGroupSearch) {
  const { scope, ready } = useCompanyQueryContext(agencyId);
  return useQuery({ queryKey: [...scope, id, "groups", params], queryFn: ({ signal }) => companiesApi.groups(agencyId!, id, params, signal), enabled: ready, ...companyQueryOptions });
}

export function useCompanyMutations(agencyId: string) {
  const client = useQueryClient();
  const invalidate = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: companyKeys.scope(agencyId) }),
      client.invalidateQueries({ queryKey: ["gc-app", agencyId] }),
      client.invalidateQueries({ queryKey: ["upload-links"] }),
    ]);
  };
  return {
    create: useMutation({ mutationFn: (body: CompanyInput) => companiesApi.create(agencyId, body), onSuccess: invalidate }),
    update: useMutation({ mutationFn: ({ id, ...body }: CompanyUpdate & { id: string }) => companiesApi.update(agencyId, id, body), onSuccess: invalidate }),
    remove: useMutation({ mutationFn: (company: Company) => companiesApi.remove(agencyId, company), onSuccess: invalidate }),
  };
}

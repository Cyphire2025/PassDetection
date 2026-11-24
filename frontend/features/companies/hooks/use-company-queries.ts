"use client";

import { useQuery } from "@tanstack/react-query";
import { companiesApi } from "../api/companies.api";
import type { CompanyGroupSearch, CompanySearch } from "../types";
import { companyQueryOptions, useCompanyQueryContext } from "./company-query-state";

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
  return useQuery({
    queryKey: [...scope, id],
    queryFn: ({ signal }) => companiesApi.get(agencyId!, id, signal),
    enabled: ready,
    ...companyQueryOptions
  });
}

export function useCompanySummary(agencyId: string | null, id: string) {
  const { scope, ready } = useCompanyQueryContext(agencyId);
  return useQuery({
    queryKey: [...scope, id, "summary"],
    queryFn: ({ signal }) => companiesApi.summary(agencyId!, id, signal),
    enabled: ready,
    ...companyQueryOptions
  });
}

export function useCompanyGroups(agencyId: string | null, id: string, params: CompanyGroupSearch) {
  const { scope, ready } = useCompanyQueryContext(agencyId);
  return useQuery({
    queryKey: [...scope, id, "groups", params],
    queryFn: ({ signal }) => companiesApi.groups(agencyId!, id, params, signal),
    enabled: ready,
    ...companyQueryOptions
  });
}

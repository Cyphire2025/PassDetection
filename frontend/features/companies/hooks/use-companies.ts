"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { companiesApi } from "../api/companies.api";
import type { Company, CompanyGroupSearch, CompanyInput, CompanySearch, CompanyUpdate } from "../types";

const queryOptions = { staleTime: 0, gcTime: 0, retry: 1 } as const;
export const companyKeys = {
  scope: (agencyId: string | null) => ["companies", agencyId] as const,
};

export function useCompanies(agencyId: string | null, params: CompanySearch) {
  return useQuery({
    queryKey: [...companyKeys.scope(agencyId), "directory", params],
    queryFn: ({ signal }) => companiesApi.list(agencyId!, params, signal),
    enabled: Boolean(agencyId),
    ...queryOptions,
  });
}

export function useCompanyLookup(agencyId: string | null, params: CompanySearch, enabled = true) {
  return useQuery({
    queryKey: [...companyKeys.scope(agencyId), "lookup", params],
    queryFn: ({ signal }) => companiesApi.lookup(agencyId!, params, signal),
    enabled: Boolean(agencyId) && enabled,
    ...queryOptions,
  });
}

export function useCompany(agencyId: string | null, id: string) {
  return useQuery({ queryKey: [...companyKeys.scope(agencyId), id], queryFn: ({ signal }) => companiesApi.get(agencyId!, id, signal), enabled: Boolean(agencyId), ...queryOptions });
}

export function useCompanySummary(agencyId: string | null, id: string) {
  return useQuery({ queryKey: [...companyKeys.scope(agencyId), id, "summary"], queryFn: ({ signal }) => companiesApi.summary(agencyId!, id, signal), enabled: Boolean(agencyId), ...queryOptions });
}

export function useCompanyGroups(agencyId: string | null, id: string, params: CompanyGroupSearch) {
  return useQuery({ queryKey: [...companyKeys.scope(agencyId), id, "groups", params], queryFn: ({ signal }) => companiesApi.groups(agencyId!, id, params, signal), enabled: Boolean(agencyId), ...queryOptions });
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

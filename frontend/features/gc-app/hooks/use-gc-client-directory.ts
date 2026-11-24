"use client";

import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { usePrivateMutation } from "@/hooks/use-private-mutation";
import { gcAppAdminApi } from "../api/gc-app-admin.api";
import type { GcCompanyReference, GcPageParams } from "../types";
import { gcAppQueryKeys } from "./gc-app-query-config";

export function useClientCompanies(
  agencyId: string | null,
  search = "",
  page = 1,
  pageSize = 50,
  enabled = true,
) {
  const params = { page, page_size: pageSize, search };
  return useQuery({
    queryKey: gcAppQueryKeys.companies(agencyId, params),
    queryFn: ({ signal }) => gcAppAdminApi.searchCompanies(agencyId, params, signal),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
  });
}

export function useClientCompanyMutations(agencyId: string | null) {
  const queryClient = useQueryClient();
  const invalidateCompanies = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: [...gcAppQueryKeys.root, agencyId, "client-companies"] }),
    queryClient.invalidateQueries({ queryKey: ["companies", agencyId] }),
  ]);
  return {
    create: usePrivateMutation({
      mutationFn: (name: string, _context, owner) => gcAppAdminApi.createClientOrganization(agencyId, name, owner.requestConfig),
      onSuccess: () => { void invalidateCompanies(); },
    }),
    remove: usePrivateMutation({
      mutationFn: (company: GcCompanyReference, _context, owner) => gcAppAdminApi.removeClientOrganization(agencyId, company.id, owner.requestConfig),
      onSuccess: () => { void invalidateCompanies(); },
    }),
  };
}

export function useGcGroupSearch(
  agencyId: string | null,
  params: GcPageParams,
  eligibleOnly: boolean,
  enabled = true,
) {
  return useQuery({
    queryKey: gcAppQueryKeys.groupSearch(agencyId, params, eligibleOnly),
    queryFn: ({ signal }) => gcAppAdminApi.searchGroups(agencyId, { ...params, eligible_only: eligibleOnly }, signal),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 2 * 60_000,
  });
}

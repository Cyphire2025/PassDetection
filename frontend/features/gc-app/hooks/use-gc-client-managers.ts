"use client";

import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { usePrivateMutation } from "@/hooks/use-private-mutation";
import { gcAppAdminApi } from "../api/gc-app-admin.api";
import type {
  ClientManagerAccount,
  ClientManagerFilters,
  ClientManagerInput,
  GcAppAccountStatus,
} from "../types";
import { gcAppQueryKeys, SECURITY_QUERY_OPTIONS } from "./gc-app-query-config";

export function useClientManagers(agencyId: string | null, filters: ClientManagerFilters) {
  return useQuery({
    queryKey: gcAppQueryKeys.clientManagers(agencyId, filters),
    queryFn: ({ signal }) => gcAppAdminApi.listClientManagers(agencyId, filters, signal),
    placeholderData: keepPreviousData,
    ...SECURITY_QUERY_OPTIONS,
  });
}

export function useClientManagerSessions(
  agencyId: string | null,
  managerId: string | null,
  page = 1,
  pageSize = 25,
) {
  const params = { page, page_size: pageSize };
  return useQuery({
    queryKey: gcAppQueryKeys.clientManagerSessions(agencyId, managerId ?? "none", params),
    queryFn: ({ signal }) =>
      gcAppAdminApi.listClientManagerSessions(agencyId, managerId!, params, signal),
    enabled: Boolean(managerId && agencyId),
    placeholderData: keepPreviousData,
    ...SECURITY_QUERY_OPTIONS,
  });
}

export function useClientManagerAudit(
  agencyId: string | null,
  managerId: string | null,
  page = 1,
  pageSize = 25,
) {
  const params = { page, page_size: pageSize };
  return useQuery({
    queryKey: gcAppQueryKeys.clientManagerAudit(agencyId, managerId ?? "none", params),
    queryFn: ({ signal }) =>
      gcAppAdminApi.listClientManagerAudit(agencyId, managerId!, params, signal),
    enabled: Boolean(managerId && agencyId),
    placeholderData: keepPreviousData,
    ...SECURITY_QUERY_OPTIONS,
  });
}

export function useClientManagerMutations(agencyId: string | null) {
  const queryClient = useQueryClient();
  const invalidateManagers = () => queryClient.invalidateQueries({
    queryKey: [...gcAppQueryKeys.root, agencyId, "client-managers"],
  });

  return {
    create: usePrivateMutation({
      mutationFn: (body: ClientManagerInput, _context, owner) => gcAppAdminApi.createClientManager(agencyId, body, owner.requestConfig),
      onSuccess: () => { void invalidateManagers(); },
    }),
    update: usePrivateMutation({
      mutationFn: ({ managerId, current, body }: {
        managerId: string;
        current: ClientManagerAccount;
        body: ClientManagerInput;
      }, _context, owner) => gcAppAdminApi.updateClientManager(agencyId, managerId, current, body, owner.requestConfig),
      // The backend intentionally uses separate revision-safe profile,
      // assignment, and password-policy mutations. Refresh even if a later
      // step fails so a successfully committed earlier step is never hidden.
      onSettled: () => { void invalidateManagers(); },
    }),
    setStatus: usePrivateMutation({
      mutationFn: ({ managerId, status, revision }: {
        managerId: string;
        status: Exclude<GcAppAccountStatus, "deleted" | "invited">;
        revision: number;
      }, _context, owner) => gcAppAdminApi.setClientManagerStatus(agencyId, managerId, status, revision, owner.requestConfig),
      onSuccess: () => { void invalidateManagers(); },
    }),
    resetPassword: usePrivateMutation({
      mutationFn: (managerId: string, _context, owner) =>
        gcAppAdminApi.resetClientManagerPassword(agencyId, managerId, owner.requestConfig),
      onSuccess: () => { void invalidateManagers(); },
    }),
    revokeSessions: usePrivateMutation({
      mutationFn: (managerId: string, _context, owner) => gcAppAdminApi.revokeClientManagerSessions(agencyId, managerId, owner.requestConfig),
      onSuccess: (_data, managerId) => {
        void invalidateManagers();
        void queryClient.invalidateQueries({ queryKey: gcAppQueryKeys.clientManagerSessions(agencyId, managerId) });
      },
    }),
    softDelete: usePrivateMutation({
      mutationFn: (managerId: string, _context, owner) => gcAppAdminApi.softDeleteClientManager(agencyId, managerId, owner.requestConfig),
      onSuccess: () => { void invalidateManagers(); },
    }),
  };
}

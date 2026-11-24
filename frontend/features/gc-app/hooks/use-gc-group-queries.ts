"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { gcAppAdminApi } from "../api/gc-app-admin.api";
import type { GcAppGroupFilters } from "../types";
import { gcAppQueryKeys, SECURITY_QUERY_OPTIONS } from "./gc-app-query-config";

export function useGcAppGroups(agencyId: string | null, filters: GcAppGroupFilters) {
  return useQuery({
    queryKey: gcAppQueryKeys.groups(agencyId, filters),
    queryFn: ({ signal }) => gcAppAdminApi.listGroups(agencyId, filters, signal),
    placeholderData: keepPreviousData,
    ...SECURITY_QUERY_OPTIONS,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });
}

export function useGcAppGroupControl(agencyId: string | null, groupId: string) {
  return useQuery({
    queryKey: gcAppQueryKeys.groupControl(agencyId, groupId),
    queryFn: ({ signal }) => gcAppAdminApi.getGroupControl(agencyId, groupId, signal),
    enabled: Boolean(groupId && agencyId),
    ...SECURITY_QUERY_OPTIONS,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });
}

export function useGcAppGroupContent(agencyId: string | null, groupId: string, enabled = true) {
  return useQuery({
    queryKey: gcAppQueryKeys.groupContent(agencyId, groupId),
    queryFn: ({ signal }) => gcAppAdminApi.getGroupContent(agencyId, groupId, signal),
    enabled: Boolean(groupId && agencyId && enabled),
    staleTime: 30_000,
  });
}

export function useGcAppGroupAudit(
  agencyId: string | null,
  groupId: string,
  page = 1,
  pageSize = 50,
  enabled = true,
) {
  const params = { page, page_size: pageSize };
  return useQuery({
    queryKey: gcAppQueryKeys.groupAudit(agencyId, groupId, params),
    queryFn: ({ signal }) =>
      gcAppAdminApi.listGroupAudit(agencyId, groupId, params, signal),
    enabled: Boolean(groupId && agencyId && enabled),
    placeholderData: keepPreviousData,
    ...SECURITY_QUERY_OPTIONS,
  });
}

export function useGcAppAnnouncements(
  agencyId: string | null, groupId: string, page = 1, pageSize = 25, enabled = true,
) {
  const params = { page, page_size: pageSize };
  return useQuery({
    queryKey: gcAppQueryKeys.groupAnnouncements(agencyId, groupId, params),
    queryFn: ({ signal }) => gcAppAdminApi.listAnnouncements(agencyId, groupId, params, signal),
    enabled: Boolean(groupId && agencyId && enabled),
    placeholderData: keepPreviousData,
    ...SECURITY_QUERY_OPTIONS,
  });
}

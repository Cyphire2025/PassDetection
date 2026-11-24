import { useQuery } from "@tanstack/react-query";
import { QUERY_KEYS } from "@/constants";
import { passportsApi } from "../api/passports.api";
import type { PassportGroupExportKind } from "../api/passports.api";
import type { PassportGroupSubmissionsViewParams } from "../api/passports.api";
import { isPassportWorkflowPending } from "../utils/passport-workflow";

export function usePassports() {
  return useQuery({
    queryKey: QUERY_KEYS.passports.list(),
    queryFn: () => passportsApi.list(),
    refetchInterval: 30_000,
  });
}

export function usePassportGroups() {
  return useQuery({
    queryKey: QUERY_KEYS.passports.groups(),
    queryFn: () => passportsApi.listGroups(),
    refetchInterval: 30_000,
  });
}

export function usePassportsByGroup(groupId: string, search?: string, includeDeleted = false) {
  return useQuery({
    queryKey: QUERY_KEYS.passports.groupDetail(groupId, { search, includeDeleted }),
    queryFn: () => passportsApi.listByGroup(groupId, search, includeDeleted),
    enabled: Boolean(groupId),
    refetchInterval: (query) => (
      query.state.data?.some((passport) => (
        isPassportWorkflowPending(passport.status, passport.extraction_status)
      ))
        ? 2_000
        : 30_000
    ),
  });
}

export function usePassportGroupExportHistory(
  groupId: string,
  kind: PassportGroupExportKind,
  page = 1,
  enabled = true,
) {
  return useQuery({
    queryKey: ["passport-export-history", groupId, kind, page],
    queryFn: () => passportsApi.getGroupExportHistory(groupId, kind, page),
    enabled: enabled && Boolean(groupId),
    staleTime: 5_000,
  });
}

export function usePassportGroupExportFields(
  groupId: string,
  enabled = true,
) {
  return useQuery({
    queryKey: ["passport-export-fields", groupId],
    queryFn: () => passportsApi.getGroupExportFields(groupId),
    enabled: enabled && Boolean(groupId),
    staleTime: 30_000,
  });
}

export function usePassportGroupExportHistoryDetail(
  groupId: string,
  historyId: string | undefined,
  page: number,
) {
  return useQuery({
    queryKey: [
      "passport-export-history",
      groupId,
      historyId ?? "closed",
      "detail",
      page,
    ],
    queryFn: () => passportsApi.getGroupExportHistoryDetail(
      groupId,
      historyId!,
      page,
    ),
    enabled: Boolean(groupId && historyId),
  });
}

export function useGroupSubmissionsView(
  groupId: string,
  params: PassportGroupSubmissionsViewParams,
  enabled = true,
) {
  return useQuery({
    queryKey: QUERY_KEYS.passports.groupDetail(groupId, {
      view: "submissions",
      ...params,
    }),
    queryFn: () => passportsApi.getGroupSubmissionsView(groupId, params),
    enabled: enabled && Boolean(groupId),
    refetchInterval: (query) => (
      query.state.data?.items.some((passport) => (
        isPassportWorkflowPending(passport.status, passport.extraction_status)
      ))
        ? 2_000
        : false
    ),
  });
}

export function useSelectedGroupsExportFields(
  groupIds: string[],
  enabled = true,
) {
  return useQuery({
    queryKey: ["passport-selected-groups-export-fields", groupIds],
    queryFn: () => passportsApi.getSelectedGroupsExportFields(groupIds),
    enabled: enabled && groupIds.length > 0,
    staleTime: 30_000,
  });
}

export function usePassportSubmission(id: string) {
  return useQuery({
    queryKey: QUERY_KEYS.passports.detail(id),
    queryFn: () => passportsApi.getById(id),
    enabled: Boolean(id),
    refetchInterval: (query) => (
      isPassportWorkflowPending(
        query.state.data?.status,
        query.state.data?.extraction_status,
      )
        ? 2_000
        : false
    ),
  });
}

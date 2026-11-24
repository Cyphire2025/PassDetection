import type { ClientManagerFilters, GcAppGroupFilters, GcPageParams } from "../types";

export const gcAppQueryKeys = {
  root: ["gc-app"] as const,
  clientManagers: (agencyId: string | null, filters: ClientManagerFilters) =>
    [...gcAppQueryKeys.root, agencyId, "client-managers", filters] as const,
  clientManagerSessions: (
    agencyId: string | null,
    managerId: string,
    params?: GcPageParams,
  ) => params
    ? [...gcAppQueryKeys.root, agencyId, "client-managers", managerId, "sessions", params] as const
    : [...gcAppQueryKeys.root, agencyId, "client-managers", managerId, "sessions"] as const,
  clientManagerAudit: (
    agencyId: string | null,
    managerId: string,
    params?: GcPageParams,
  ) => params
    ? [...gcAppQueryKeys.root, agencyId, "client-managers", managerId, "audit", params] as const
    : [...gcAppQueryKeys.root, agencyId, "client-managers", managerId, "audit"] as const,
  companies: (agencyId: string | null, params: GcPageParams) =>
    [...gcAppQueryKeys.root, agencyId, "client-companies", params] as const,
  groupSearch: (agencyId: string | null, params: GcPageParams, eligibleOnly: boolean) =>
    [...gcAppQueryKeys.root, agencyId, "group-search", params, eligibleOnly] as const,
  groups: (agencyId: string | null, filters: GcAppGroupFilters) =>
    [...gcAppQueryKeys.root, agencyId, "groups", filters] as const,
  groupControl: (agencyId: string | null, groupId: string) =>
    [...gcAppQueryKeys.root, agencyId, "groups", groupId, "control"] as const,
  groupContent: (agencyId: string | null, groupId: string) =>
    [...gcAppQueryKeys.root, agencyId, "groups", groupId, "content"] as const,
  groupAnnouncements: (agencyId: string | null, groupId: string, params?: GcPageParams) => params
    ? [...gcAppQueryKeys.root, agencyId, "groups", groupId, "announcements", params] as const
    : [...gcAppQueryKeys.root, agencyId, "groups", groupId, "announcements"] as const,
  groupAudit: (agencyId: string | null, groupId: string, params?: GcPageParams) => params
    ? [...gcAppQueryKeys.root, agencyId, "groups", groupId, "audit", params] as const
    : [...gcAppQueryKeys.root, agencyId, "groups", groupId, "audit"] as const,
};

export const SECURITY_QUERY_OPTIONS = {
  // Sensitive data stays in the authenticated in-memory query cache only.
  // A short freshness window prevents navigation/focus request storms while
  // still reconciling access changes promptly in the background.
  staleTime: 30_000,
  gcTime: 10 * 60_000,
  refetchOnWindowFocus: true,
  retry: 1,
} as const;

"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { gcAppAdminApi } from "../api/gc-app-admin.api";
import type {
  AnnouncementInput,
  ClientManagerAccount,
  ClientManagerFilters,
  ClientManagerInput,
  CommonDocumentUpload,
  GcAppAccountStatus,
  GcAppControlPatch,
  GcAppGroupFilters,
  GcAppGroupControl,
  GcCompanyReference,
  GcGroupReference,
  GcPageParams,
  StructuredItinerary,
} from "../types";

export const gcAppQueryKeys = {
  root: ["gc-app"] as const,
  clientManagers: (agencyId: string | null, filters: ClientManagerFilters) =>
    [...gcAppQueryKeys.root, agencyId, "client-managers", filters] as const,
  clientManagerSessions: (agencyId: string | null, managerId: string) =>
    [...gcAppQueryKeys.root, agencyId, "client-managers", managerId, "sessions"] as const,
  clientManagerAudit: (agencyId: string | null, managerId: string) =>
    [...gcAppQueryKeys.root, agencyId, "client-managers", managerId, "audit"] as const,
  companies: (agencyId: string | null, search: string) =>
    [...gcAppQueryKeys.root, agencyId, "client-companies", search] as const,
  groupSearch: (agencyId: string | null, params: GcPageParams, eligibleOnly: boolean) =>
    [...gcAppQueryKeys.root, agencyId, "group-search", params, eligibleOnly] as const,
  groups: (agencyId: string | null, filters: GcAppGroupFilters) =>
    [...gcAppQueryKeys.root, agencyId, "groups", filters] as const,
  groupControl: (agencyId: string | null, groupId: string) =>
    [...gcAppQueryKeys.root, agencyId, "groups", groupId, "control"] as const,
  groupContent: (agencyId: string | null, groupId: string) =>
    [...gcAppQueryKeys.root, agencyId, "groups", groupId, "content"] as const,
  groupAudit: (agencyId: string | null, groupId: string) =>
    [...gcAppQueryKeys.root, agencyId, "groups", groupId, "audit"] as const,
};

const SECURITY_QUERY_OPTIONS = {
  staleTime: 0,
  refetchOnWindowFocus: true,
  retry: 1,
} as const;

export function useClientManagers(agencyId: string | null, filters: ClientManagerFilters) {
  return useQuery({
    queryKey: gcAppQueryKeys.clientManagers(agencyId, filters),
    queryFn: ({ signal }) => gcAppAdminApi.listClientManagers(agencyId, filters, signal),
    placeholderData: keepPreviousData,
    ...SECURITY_QUERY_OPTIONS,
  });
}

export function useClientManagerSessions(agencyId: string | null, managerId: string | null) {
  return useQuery({
    queryKey: gcAppQueryKeys.clientManagerSessions(agencyId, managerId ?? "none"),
    queryFn: ({ signal }) => gcAppAdminApi.listClientManagerSessions(agencyId, managerId!, signal),
    enabled: Boolean(managerId && agencyId),
    ...SECURITY_QUERY_OPTIONS,
  });
}

export function useClientManagerAudit(agencyId: string | null, managerId: string | null) {
  return useQuery({
    queryKey: gcAppQueryKeys.clientManagerAudit(agencyId, managerId ?? "none"),
    queryFn: ({ signal }) => gcAppAdminApi.listClientManagerAudit(agencyId, managerId!, signal),
    enabled: Boolean(managerId && agencyId),
    ...SECURITY_QUERY_OPTIONS,
  });
}

export function useClientCompanies(agencyId: string | null, search = "") {
  return useQuery({
    queryKey: gcAppQueryKeys.companies(agencyId, search),
    queryFn: ({ signal }) => gcAppAdminApi.searchCompanies(agencyId, search, signal),
    staleTime: 60_000,
  });
}

export function useClientCompanyMutations(agencyId: string | null) {
  const queryClient = useQueryClient();
  const invalidateCompanies = () => queryClient.invalidateQueries({
    queryKey: [...gcAppQueryKeys.root, agencyId, "client-companies"],
  });
  return {
    create: useMutation({
      mutationFn: (name: string) => gcAppAdminApi.createClientOrganization(agencyId, name),
      onSuccess: invalidateCompanies,
    }),
    remove: useMutation({
      mutationFn: (company: GcCompanyReference) => gcAppAdminApi.removeClientOrganization(agencyId, company.id),
      onSuccess: invalidateCompanies,
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
    staleTime: 30_000,
  });
}

export function useClientManagerMutations(agencyId: string | null) {
  const queryClient = useQueryClient();
  const invalidateManagers = () => queryClient.invalidateQueries({
    queryKey: [...gcAppQueryKeys.root, agencyId, "client-managers"],
  });

  return {
    create: useMutation({
      mutationFn: (body: ClientManagerInput) => gcAppAdminApi.createClientManager(agencyId, body),
      onSuccess: invalidateManagers,
    }),
    update: useMutation({
      mutationFn: ({ managerId, current, body }: {
        managerId: string;
        current: ClientManagerAccount;
        body: Omit<ClientManagerInput, "activation_method" | "temporary_password">;
      }) => gcAppAdminApi.updateClientManager(agencyId, managerId, current, body),
      // The backend intentionally uses separate revision-safe profile,
      // assignment, and password-policy mutations. Refresh even if a later
      // step fails so a successfully committed earlier step is never hidden.
      onSettled: invalidateManagers,
    }),
    setStatus: useMutation({
      mutationFn: ({ managerId, status, revision }: {
        managerId: string;
        status: Exclude<GcAppAccountStatus, "deleted" | "invited">;
        revision: number;
      }) => gcAppAdminApi.setClientManagerStatus(agencyId, managerId, status, revision),
      onSuccess: invalidateManagers,
    }),
    resetPassword: useMutation({
      mutationFn: ({ managerId, temporaryPassword }: { managerId: string; temporaryPassword: string }) =>
        gcAppAdminApi.resetClientManagerPassword(agencyId, managerId, temporaryPassword),
      onSuccess: invalidateManagers,
    }),
    revokeSessions: useMutation({
      mutationFn: (managerId: string) => gcAppAdminApi.revokeClientManagerSessions(agencyId, managerId),
      onSuccess: (_data, managerId) => Promise.all([
        invalidateManagers(),
        queryClient.invalidateQueries({ queryKey: gcAppQueryKeys.clientManagerSessions(agencyId, managerId) }),
      ]),
    }),
    softDelete: useMutation({
      mutationFn: (managerId: string) => gcAppAdminApi.softDeleteClientManager(agencyId, managerId),
      onSuccess: invalidateManagers,
    }),
  };
}

export function useGcAppGroups(agencyId: string | null, filters: GcAppGroupFilters) {
  return useQuery({
    queryKey: gcAppQueryKeys.groups(agencyId, filters),
    queryFn: ({ signal }) => gcAppAdminApi.listGroups(agencyId, filters, signal),
    placeholderData: keepPreviousData,
    ...SECURITY_QUERY_OPTIONS,
  });
}

export function useGcAppGroupControl(agencyId: string | null, groupId: string) {
  return useQuery({
    queryKey: gcAppQueryKeys.groupControl(agencyId, groupId),
    queryFn: ({ signal }) => gcAppAdminApi.getGroupControl(agencyId, groupId, signal),
    enabled: Boolean(groupId && agencyId),
    ...SECURITY_QUERY_OPTIONS,
  });
}

export function useGcAppGroupContent(agencyId: string | null, groupId: string, enabled = true) {
  return useQuery({
    queryKey: gcAppQueryKeys.groupContent(agencyId, groupId),
    queryFn: ({ signal }) => gcAppAdminApi.getGroupContent(agencyId, groupId, signal),
    enabled: Boolean(groupId && agencyId && enabled),
    staleTime: 15_000,
  });
}

export function useGcAppGroupAudit(agencyId: string | null, groupId: string) {
  return useQuery({
    queryKey: gcAppQueryKeys.groupAudit(agencyId, groupId),
    queryFn: ({ signal }) => gcAppAdminApi.listGroupAudit(agencyId, groupId, signal),
    enabled: Boolean(groupId && agencyId),
    ...SECURITY_QUERY_OPTIONS,
  });
}

export function useGcAppGroupMutations(agencyId: string | null, groupId?: string, accessRevision?: number) {
  const queryClient = useQueryClient();
  const invalidateGroupLists = () => Promise.all([
    queryClient.invalidateQueries({
      queryKey: [...gcAppQueryKeys.root, agencyId, "groups"],
    }),
    queryClient.invalidateQueries({
      queryKey: [...gcAppQueryKeys.root, agencyId, "group-search"],
    }),
  ]);
  const invalidateControl = (id: string) => Promise.all([
    invalidateGroupLists(),
    queryClient.invalidateQueries({ queryKey: gcAppQueryKeys.groupControl(agencyId, id) }),
    queryClient.invalidateQueries({ queryKey: gcAppQueryKeys.groupAudit(agencyId, id) }),
  ]);
  const invalidateContent = (id: string) => Promise.all([
    queryClient.invalidateQueries({ queryKey: gcAppQueryKeys.groupContent(agencyId, id) }),
    queryClient.invalidateQueries({ queryKey: gcAppQueryKeys.groupControl(agencyId, id) }),
    queryClient.invalidateQueries({ queryKey: gcAppQueryKeys.groupAudit(agencyId, id) }),
    invalidateGroupLists(),
  ]);

  return {
    add: useMutation({
      mutationFn: ({ group, company }: { group: GcGroupReference; company: GcCompanyReference }) =>
        gcAppAdminApi.addGroup(agencyId, group, company),
      onSuccess: invalidateGroupLists,
    }),
    remove: useMutation({
      mutationFn: (control: GcAppGroupControl) => gcAppAdminApi.removeGroup(agencyId, control),
      onSuccess: (_data, control) => invalidateControl(control.id),
    }),
    updateControl: useMutation({
      mutationFn: ({ control, patch }: { control: GcAppGroupControl; patch: GcAppControlPatch }) =>
        gcAppAdminApi.updateGroupControl(agencyId, control, patch),
      onSuccess: (_data, variables) => invalidateControl(variables.control.id),
    }),
    revoke: useMutation({
      mutationFn: (id: string) => gcAppAdminApi.revokeGroupAccess(agencyId, id),
      onSuccess: (_data, id) => invalidateControl(id),
    }),
    saveItinerary: useMutation({
      mutationFn: (itinerary: StructuredItinerary) => gcAppAdminApi.saveItineraryDraft(agencyId, groupId!, itinerary, requireAccessRevision(accessRevision)),
      onSuccess: () => invalidateContent(groupId!),
    }),
    publishItinerary: useMutation({
      mutationFn: (versionId: string) => gcAppAdminApi.publishItinerary(agencyId, groupId!, versionId),
      onSuccess: () => invalidateContent(groupId!),
    }),
    unpublishItinerary: useMutation({
      mutationFn: (versionId: string) => gcAppAdminApi.unpublishItinerary(agencyId, groupId!, versionId),
      onSuccess: () => invalidateContent(groupId!),
    }),
    uploadDocument: useMutation({
      mutationFn: (upload: CommonDocumentUpload) => gcAppAdminApi.uploadCommonDocument(agencyId, groupId!, upload, requireAccessRevision(accessRevision)),
      onSuccess: () => invalidateContent(groupId!),
    }),
    setDocumentPublished: useMutation({
      mutationFn: ({ documentId, published }: { documentId: string; published: boolean }) =>
        gcAppAdminApi.setCommonDocumentPublished(agencyId, groupId!, documentId, published),
      onSuccess: () => invalidateContent(groupId!),
    }),
    previewDocument: useMutation({
      mutationFn: (documentId: string) => gcAppAdminApi.previewCommonDocument(
        agencyId,
        groupId!,
        documentId,
      ),
    }),
    reorderDocuments: useMutation({
      mutationFn: (orderedDocumentIds: string[]) => gcAppAdminApi.reorderCommonDocuments(
        agencyId,
        groupId!,
        orderedDocumentIds,
        requireAccessRevision(accessRevision),
      ),
      onSuccess: () => invalidateContent(groupId!),
    }),
    deleteDocument: useMutation({
      mutationFn: (documentId: string) => gcAppAdminApi.deleteCommonDocument(agencyId, groupId!, documentId),
      onSuccess: () => invalidateContent(groupId!),
    }),
    createAnnouncement: useMutation({
      mutationFn: (body: AnnouncementInput) => gcAppAdminApi.createAnnouncement(agencyId, groupId!, body, requireAccessRevision(accessRevision)),
      onSuccess: () => invalidateContent(groupId!),
    }),
    updateAnnouncement: useMutation({
      mutationFn: ({ announcementId, body }: { announcementId: string; body: AnnouncementInput }) =>
        gcAppAdminApi.updateAnnouncement(agencyId, groupId!, announcementId, body, requireAccessRevision(accessRevision)),
      onSuccess: () => invalidateContent(groupId!),
    }),
    setAnnouncementPublished: useMutation({
      mutationFn: ({ announcementId, published }: { announcementId: string; published: boolean }) =>
        gcAppAdminApi.setAnnouncementPublished(agencyId, groupId!, announcementId, published),
      onSuccess: () => invalidateContent(groupId!),
    }),
    deleteAnnouncement: useMutation({
      mutationFn: (announcementId: string) => gcAppAdminApi.deleteAnnouncement(agencyId, groupId!, announcementId),
      onSuccess: () => invalidateContent(groupId!),
    }),
  };
}

function requireAccessRevision(revision: number | undefined): number {
  if (revision === undefined) throw new Error("GC App access revision is unavailable. Refresh and try again.");
  return revision;
}

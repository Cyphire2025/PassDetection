"use client";

import { useQueryClient } from "@tanstack/react-query";
import { usePrivateMutation } from "@/hooks/use-private-mutation";
import { gcAppAdminApi } from "../api/gc-app-admin.api";
import type {
  AnnouncementInput,
  CommonDocumentUpload,
  GcAppControlPatch,
  GcAppGroupContent,
  GcAppGroupControl,
  GcAnnouncement,
  GcCompanyReference,
  GcGroupReference,
  StructuredItinerary,
} from "../types";
import type { MutationFunctionContext } from "@tanstack/react-query";
import type { PrivateOperationOwner } from "@/hooks/use-private-mutation";
import { gcAppQueryKeys } from "./gc-app-query-config";

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
    queryClient.invalidateQueries({ queryKey: gcAppQueryKeys.groupAnnouncements(agencyId, id) }),
    invalidateGroupLists(),
  ]);
  const refreshControl = (id: string) => { void invalidateControl(id).catch(() => undefined); };
  const refreshContent = () => { void invalidateContent(groupId!).catch(() => undefined); };
  const acceptControl = async (updated: GcAppGroupControl, _variables: unknown, _result: unknown, _context: MutationFunctionContext, owner: PrivateOperationOwner) => {
    owner.assertCurrent();
    const key = gcAppQueryKeys.groupControl(agencyId, updated.id);
    await queryClient.cancelQueries({ queryKey: key });
    owner.assertCurrent();
    queryClient.setQueryData<GcAppGroupControl>(key, (current) => (
      current && current.revision > updated.revision ? current : updated
    ));
    refreshControl(updated.id);
  };
  const acceptAnnouncement = async (updated: GcAnnouncement, owner: PrivateOperationOwner, previousId?: string) => {
    owner.assertCurrent();
    const key = gcAppQueryKeys.groupContent(agencyId, groupId!);
    await queryClient.cancelQueries({ queryKey: key });
    owner.assertCurrent();
    queryClient.setQueryData<GcAppGroupContent>(key, (current) => current ? {
      ...current,
      announcements: [updated, ...current.announcements.filter((item) => (
        item.id !== updated.id
        && (item.id !== previousId || (!updated.is_published && item.is_published))
      ))],
    } : current);
  };

  return {
    add: usePrivateMutation({
      mutationFn: ({ group, company }: { group: GcGroupReference; company: GcCompanyReference }, _context, owner) =>
        gcAppAdminApi.addGroup(agencyId, group, company, owner.requestConfig),
      onSuccess: acceptControl,
      onError: () => { void invalidateGroupLists().catch(() => undefined); },
    }),
    remove: usePrivateMutation({
      mutationFn: (control: GcAppGroupControl, _context, owner) => gcAppAdminApi.removeGroup(agencyId, control, owner.requestConfig),
      retry: false,
      onSettled: (_data, _error, control) => refreshControl(control.id),
    }),
    updateControl: usePrivateMutation({
      mutationFn: ({ control, patch }: { control: GcAppGroupControl; patch: GcAppControlPatch }, _context, owner) =>
        gcAppAdminApi.updateGroupControl(agencyId, control, patch, owner.requestConfig),
      onSuccess: acceptControl,
      onError: (_error, variables) => refreshControl(variables.control.id),
    }),
    setMyPhotosEnabled: usePrivateMutation({
      mutationFn: ({ control, enabled }: { control: GcAppGroupControl; enabled: boolean }, _context, owner) =>
        gcAppAdminApi.setMyPhotosEnabled(agencyId, control, enabled, owner.requestConfig),
      onSuccess: acceptControl,
      onError: (_error, variables) => {
        // A revision conflict must show the latest authoritative state. Never
        // retry a stale full intent automatically because another operator may
        // have changed access settings in the meantime.
        void invalidateControl(variables.control.id).catch(() => undefined);
      },
    }),
    revoke: usePrivateMutation({
      mutationFn: (id: string, _context, owner) => gcAppAdminApi.revokeGroupAccess(agencyId, id, owner.requestConfig),
      onSuccess: (_data, id) => { void invalidateControl(id); },
    }),
    saveItinerary: usePrivateMutation({
      mutationFn: (itinerary: StructuredItinerary, _context, owner) => gcAppAdminApi.saveItineraryDraft(agencyId, groupId!, itinerary, requireAccessRevision(accessRevision), owner.requestConfig),
      onSuccess: () => { void invalidateContent(groupId!); },
    }),
    publishItinerary: usePrivateMutation({
      mutationFn: (versionId: string, _context, owner) => gcAppAdminApi.publishItinerary(agencyId, groupId!, versionId, owner.requestConfig),
      onSuccess: () => { void invalidateContent(groupId!); },
    }),
    unpublishItinerary: usePrivateMutation({
      mutationFn: (versionId: string, _context, owner) => gcAppAdminApi.unpublishItinerary(agencyId, groupId!, versionId, owner.requestConfig),
      onSuccess: () => { void invalidateContent(groupId!); },
    }),
    uploadDocument: usePrivateMutation({
      mutationFn: (upload: CommonDocumentUpload, _context, owner) => gcAppAdminApi.uploadCommonDocument(agencyId, groupId!, upload, requireAccessRevision(accessRevision), owner.requestConfig),
      onSuccess: async (uploadedDocument, upload, _result, _context, owner) => {
        owner.assertCurrent();
        // The upload command has already succeeded at this point. Do not keep
        // the button in a pending state while unrelated group/audit queries
        // refetch. Surface the returned draft immediately, then reconcile all
        // version counters and access revisions in the background.
        await queryClient.cancelQueries({ queryKey: gcAppQueryKeys.groupContent(agencyId, groupId!) });
        owner.assertCurrent();
        queryClient.setQueryData<GcAppGroupContent>(
          gcAppQueryKeys.groupContent(agencyId, groupId!),
          (current) => {
            if (!current) return current;
            const retainedDocuments = current.common_documents.filter(
              (document) => document.id !== uploadedDocument.id
                && (document.id !== upload.replace_document_id || document.is_published),
            );
            return {
              ...current,
              common_documents: [uploadedDocument, ...retainedDocuments],
            };
          },
        );
        void invalidateContent(groupId!).catch(() => undefined);
      },
      onError: refreshContent,
    }),
    setDocumentPublished: usePrivateMutation({
      mutationFn: ({ documentId, published }: { documentId: string; published: boolean }, _context, owner) =>
        gcAppAdminApi.setCommonDocumentPublished(agencyId, groupId!, documentId, published, owner.requestConfig),
      onSettled: refreshContent,
    }),
    previewDocument: usePrivateMutation({
      mutationFn: (documentId: string, _context, owner) => gcAppAdminApi.previewCommonDocument(
        agencyId,
        groupId!,
        documentId, undefined, owner.requestConfig,
      ),
    }),
    reorderDocuments: usePrivateMutation({
      mutationFn: (orderedDocumentIds: string[], _context, owner) => gcAppAdminApi.reorderCommonDocuments(
        agencyId,
        groupId!,
        orderedDocumentIds,
        requireAccessRevision(accessRevision), owner.requestConfig,
      ),
      onSettled: refreshContent,
    }),
    deleteDocument: usePrivateMutation({
      mutationFn: (documentId: string, _context, owner) => gcAppAdminApi.deleteCommonDocument(agencyId, groupId!, documentId, owner.requestConfig),
      onSettled: refreshContent,
    }),
    createAnnouncement: usePrivateMutation({
      mutationFn: (body: AnnouncementInput, _context, owner) => gcAppAdminApi.createAnnouncement(agencyId, groupId!, body, requireAccessRevision(accessRevision), owner.requestConfig),
      onSuccess: (updated, _variables, _result, _context, owner) => acceptAnnouncement(updated, owner),
      onSettled: refreshContent,
    }),
    updateAnnouncement: usePrivateMutation({
      mutationFn: ({ announcementId, body }: { announcementId: string; body: AnnouncementInput }, _context, owner) =>
        gcAppAdminApi.updateAnnouncement(agencyId, groupId!, announcementId, body, requireAccessRevision(accessRevision), owner.requestConfig),
      onSuccess: (updated, variables, _result, _context, owner) => acceptAnnouncement(updated, owner, variables.announcementId),
      onSettled: refreshContent,
    }),
    setAnnouncementPublished: usePrivateMutation({
      mutationFn: ({ announcementId, published }: { announcementId: string; published: boolean }, _context, owner) =>
        gcAppAdminApi.setAnnouncementPublished(agencyId, groupId!, announcementId, published, owner.requestConfig),
      onSettled: refreshContent,
    }),
    deleteAnnouncement: usePrivateMutation({
      mutationFn: (announcementId: string, _context, owner) => gcAppAdminApi.deleteAnnouncement(agencyId, groupId!, announcementId, owner.requestConfig),
      onSuccess: (_result, announcementId, _onMutateResult, _context, owner) => {
        owner.assertCurrent();
        queryClient.setQueryData<GcAppGroupContent>(
          gcAppQueryKeys.groupContent(agencyId, groupId!),
          (current) => current ? {
            ...current,
            announcements: current.announcements.filter(
              (announcement) => announcement.id !== announcementId,
            ),
          } : current,
        );
        void invalidateContent(groupId!);
      },
      onError: refreshContent,
    }),
  };
}

function requireAccessRevision(revision: number | undefined): number {
  if (revision === undefined) throw new Error("GC App access revision is unavailable. Refresh and try again.");
  return revision;
}

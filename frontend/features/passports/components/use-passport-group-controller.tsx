"use client";

import { usePassportGroupSelection } from "./use-passport-group-selection";
import { canAccessWhatsAppBroadcasts, canDeletePassportSubmissions } from "@/lib/utils/role-access";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import {
  useBulkDeletePassportSubmissions,
  useBulkStaffApprovePassportSubmissions,
  useExportPassportGroup,
  useExportPassportGroupImages,
  useExportSelectedPassports,
} from "../hooks/use-passports";
import { useUpdateUploadLink } from "../hooks/use-upload-links";
import { canEditPassportImages } from "../utils/passport-image-crop-permissions";
import { usePassportDocumentFollowUp } from "./use-passport-document-follow-up";
import { usePassportGroupView } from "./use-passport-group-view";
import { usePassportGroupMetadata } from "./use-passport-group-metadata";
import { usePassportGroupMenus } from "./use-passport-group-menus";
import { usePassportGroupImports } from "./use-passport-group-imports";
import { usePassportGroupDialogState } from "./use-passport-group-dialog-state";
import { usePassportSelectedImageDownload } from "./use-passport-selected-image-download";

export function usePassportGroupController({ groupId }: {
  groupId: string;
}) {
  const currentUser = useAuthStore(selectUser);
  const role = currentUser?.role ?? null;
  const canPermanentlyDelete = canDeletePassportSubmissions(role);
  const canBulkStaffApprove = role === "super_admin" || role === "agency_admin"
    || role === "agency_manager" || role === "agency_staff";
  const canEditImages = canEditPassportImages(role);
  const canAccessWhatsApp = canAccessWhatsAppBroadcasts(role);
  const view = usePassportGroupView(groupId, currentUser?.id ?? null);
  const { isPlaceholderData, ...publicView } = view;
  const metadata = usePassportGroupMetadata(groupId, view.includeDeleted);
  const menus = usePassportGroupMenus();
  const imports = usePassportGroupImports(groupId);
  const dialogs = usePassportGroupDialogState();
  const selection = usePassportGroupSelection(view.submissionsView, () => menus.setIsBulkActionsMenuOpen(false));
  const downloads = usePassportSelectedImageDownload(groupId, metadata.groupDetails?.group_name, selection.selectedPassports, imports.setImportMessage);
  const exportMutation = useExportPassportGroup();
  const exportImagesMutation = useExportPassportGroupImages();
  const exportSelected = useExportSelectedPassports();
  const bulkDelete = useBulkDeletePassportSubmissions(groupId);
  const bulkStaffApprove = useBulkStaffApprovePassportSubmissions(groupId);
  const updateGroup = useUpdateUploadLink();
  const documentFollowUp = usePassportDocumentFollowUp({
    groupId,
    selectedPassports: selection.selectedPassports,
    submissionFilter: view.submissionFilter,
    setSubmissionFilter: view.setSubmissionFilter,
    setPage: view.setPage,
    canManage: canBulkStaffApprove,
    includeDeleted: view.includeDeleted,
    groupStatus: metadata.groupDetails?.group_status,
    flaggedCount: view.submissionsView?.document_follow_up_count,
    viewStatus: { isLoading: view.isLoading, isFetching: view.isFetching, isPlaceholderData, error: view.error },
    setFeedback: selection.setBulkDeleteFeedback,
    closeMenu: () => menus.setIsBulkActionsMenuOpen(false),
  });
  return {
    ...publicView,
    ...metadata,
    ...menus,
    ...imports,
    ...dialogs,
    ...selection,
    ...downloads,
    documentFollowUp,
    groupId,
    canPermanentlyDelete,
    canBulkStaffApprove,
    canEditImages,
    canAccessWhatsApp,
    canEditDisplayName: documentFollowUp.canManage && metadata.groupDetails?.group_status !== "deleted",
    exportMutation,
    exportImagesMutation,
    exportSelected,
    bulkDelete,
    bulkStaffApprove,
    updateGroup,
  };
}
export type PassportGroupController = ReturnType<typeof usePassportGroupController>;

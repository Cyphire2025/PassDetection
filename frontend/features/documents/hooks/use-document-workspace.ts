"use client";
import { useState } from "react";
import type { DocumentPassengerReviewRow } from "@/types/document-distribution.types";
import type { DocumentDistributionLane } from "../config/document-distribution-lanes";
import {
  useDocumentGroups, useDocumentReview, useExportDocumentAssignments,
  useAbortDistributionUploads, useDeleteDistributionDocuments, useReuploadPassengerDocument,
  useManualPassengerDocumentUpload, useSaveDocumentBatch, useUnassignDistributionDocuments
} from "./use-document-distribution";
import { useDocumentWorkspaceUpload } from "./use-document-workspace-upload";
import { useDocumentWorkspaceSelection } from "./use-document-workspace-selection";
import { useDocumentWorkspaceDelivery } from "./use-document-workspace-delivery";

export function useDocumentWorkspace(groupId: string, lane: DocumentDistributionLane) {
  const documentType = lane.documentType;
  const [manualUploadTarget, setManualUploadTarget] = useState<{ row: DocumentPassengerReviewRow; mode: "add" | "replace" } | null>(null);
  const { data: groups = [] } = useDocumentGroups();
  const group = groups.find((item) => item.group_id === groupId);
  const review = useDocumentReview(groupId, documentType);
  const exportAssignments = useExportDocumentAssignments(groupId, documentType, group?.group_name);
  const uploadWorkflow = useDocumentWorkspaceUpload(groupId, documentType, review, setManualUploadTarget);
  const { phase, preparingCheck, verify, manualReview, upload } = uploadWorkflow;
  const selection = useDocumentWorkspaceSelection(review, documentType);
  const delivery = useDocumentWorkspaceDelivery(groupId, lane, group?.group_name);
  const { sendDocuments } = delivery;
  const abortUploads = useAbortDistributionUploads(groupId, documentType);
  const reupload = useReuploadPassengerDocument(groupId, documentType);
  const manualUpload = useManualPassengerDocumentUpload(groupId, documentType);
  const deleteDocuments = useDeleteDistributionDocuments(groupId, documentType);
  const unassignDocuments = useUnassignDistributionDocuments(groupId, documentType);
  const save = useSaveDocumentBatch(groupId, documentType);
  const documentTypeOperationPending =
    phase !== "idle" ||
    preparingCheck ||
    verify.isPending ||
    manualReview.pending ||
    upload.isPending ||
    abortUploads.isPending ||
    reupload.isPending ||
    manualUpload.isPending ||
    deleteDocuments.isPending ||
    unassignDocuments.isPending ||
    save.isPending ||
    sendDocuments.isPending;
  const hasUncommittedSelection =
    uploadWorkflow.selectedFiles.length > 0 || (uploadWorkflow.stagingManifest?.totalFiles ?? 0) > 0
    || manualReview.candidates.size > 0 || manualReview.pendingUpload !== null;
  const manualReviewDisabled = documentTypeOperationPending || uploadWorkflow.manualReviewLocked;
  const removalPending = deleteDocuments.isPending || unassignDocuments.isPending;
  return {
    ...uploadWorkflow, ...selection, ...delivery,
    groupId, lane, documentType, group, review, exportAssignments, abortUploads, reupload, manualUpload,
    deleteDocuments, unassignDocuments, save, manualUploadTarget, setManualUploadTarget,
    documentTypeOperationPending, hasUncommittedSelection, manualReviewDisabled, removalPending,
  };
}
export type DocumentWorkspaceController = ReturnType<typeof useDocumentWorkspace>;

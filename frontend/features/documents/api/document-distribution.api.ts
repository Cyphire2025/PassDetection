import apiClient, { type ApiError } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { downloadStreamedResponse } from "@/lib/api/streamed-download";
import type {
  AbortDocumentUploadResult,
  DistributionDocumentType,
  DocumentBatchReview,
  DocumentDistributionGroup,
  DocumentDeliveryPreview,
  DocumentDeliveryTracking,
  DocumentVerificationResult,
  SendDocumentBroadcastResult,
} from "@/types/document-distribution.types";
import {
  createDocumentStagingManifest,
  createDocumentVerificationSession,
  isPassengerMatchedVerificationFile,
  MAX_DOCUMENT_VERIFICATION_CONCURRENCY,
  runConcurrentDocumentVerification,
  runStagedDocumentUpload,
  type DocumentStagingManifest,
  type DocumentUploadProgress,
} from "../services/document-upload-batching";
import { verificationWithoutStagingReceipts } from "../services/document-upload-recovery";

export interface DocumentVerificationUploadPlan {
  verification: DocumentVerificationResult;
  stagingManifest: DocumentStagingManifest;
}

export type DocumentAssignmentExportFilter =
  | "all"
  | "assigned"
  | "missing"
  | "sent"
  | "not_sent";

export const documentDistributionApi = {
  listGroups: async (search?: string, signal?: AbortSignal): Promise<DocumentDistributionGroup[]> => {
    const { data } = await apiClient.get<DocumentDistributionGroup[]>(API_ENDPOINTS.documents.groups, {
      params: search?.trim() ? { search: search.trim() } : undefined,
      signal,
    });
    return data;
  },

  getReview: async (groupId: string, documentType: DistributionDocumentType): Promise<DocumentBatchReview> => {
    const { data } = await apiClient.get<DocumentBatchReview>(API_ENDPOINTS.documents.review(groupId, documentType));
    return data;
  },

  exportReview: async (
    groupId: string,
    documentType: DistributionDocumentType,
    filter: DocumentAssignmentExportFilter,
    search: string,
    groupName?: string,
  ): Promise<void> => {
    await downloadStreamedResponse({
      url: API_ENDPOINTS.documents.reviewExport(groupId, documentType),
      params: { filter, search: search.trim() || undefined },
      suggestedFilename: documentAssignmentFilename(
        groupName ?? groupId,
        documentType,
        filter,
      ),
    });
  },

  verifyDocuments: async (
    groupId: string,
    documentType: DistributionDocumentType,
    files: File[],
    onProgress?: (progress: DocumentUploadProgress) => void,
    signal?: AbortSignal,
  ): Promise<DocumentVerificationUploadPlan> => {
    const session = createDocumentVerificationSession(files);
    const completedResults = await runConcurrentDocumentVerification({
      session,
      concurrency: MAX_DOCUMENT_VERIFICATION_CONCURRENCY,
      onProgress,
      signal,
      uploadChunk: async (chunk, chunkIndex, reportUpload) => {
        const formData = new FormData();
        formData.append("upload_id", session.uploadId);
        formData.append("chunk_id", session.chunkIds[chunkIndex]);
        chunk.forEach((file) => formData.append("files", file));
        const { data } = await apiClient.post<DocumentVerificationResult>(
          API_ENDPOINTS.documents.verify(groupId, documentType),
          formData,
          {
            headers: { "Content-Type": "multipart/form-data" },
            timeout: 240_000,
            signal,
            onUploadProgress: (event) => reportUpload(event.loaded, event.total),
          },
        );
        return data;
      },
    });
    const normalizedResults = completedResults.map((result) => {
      const verifiedFiles = result.files.map((file) => {
        const accepted = isPassengerMatchedVerificationFile(file);
        if (accepted === file.accepted) return file;
        return {
          ...file,
          accepted,
          reason: file.match_reason || "No passenger match found",
          staging_receipt: null,
        };
      });
      const acceptedCount = verifiedFiles.filter((file) => file.accepted).length;
      return {
        ...result,
        accepted_count: acceptedCount,
        rejected_count: verifiedFiles.length - acceptedCount,
        files: verifiedFiles,
      };
    });
    const stagingManifest = createDocumentStagingManifest(
      session,
      normalizedResults.map((result) => result.files.map((file) => file.accepted)),
      normalizedResults.map((result) =>
        result.files.map((file) => file.staging_receipt),
      ),
    );
    const verification = verificationWithoutStagingReceipts({
      group_id: groupId,
      document_type: documentType,
      total_count: normalizedResults.reduce(
        (total, result) => total + result.total_count,
        0,
      ),
      accepted_count: normalizedResults.reduce(
        (total, result) => total + result.accepted_count,
        0,
      ),
      rejected_count: normalizedResults.reduce(
        (total, result) => total + result.rejected_count,
        0,
      ),
      files: normalizedResults.flatMap((result) => result.files),
    });
    return {
      stagingManifest,
      verification,
    };
  },

  uploadDocuments: async (
    groupId: string,
    documentType: DistributionDocumentType,
    manifest: DocumentStagingManifest,
    onProgress?: (progress: DocumentUploadProgress) => void,
    onManifestChange?: (manifest: DocumentStagingManifest) => void,
    signal?: AbortSignal,
  ): Promise<DocumentBatchReview> => {
    return runStagedDocumentUpload({
      manifest,
      onProgress,
      onManifestChange,
      signal,
      uploadChunk: async (chunk, chunkIndex, reportUpload) => {
        const formData = new FormData();
        formData.append("upload_id", manifest.uploadId);
        formData.append("chunk_id", chunk.chunkId);
        formData.append("chunk_index", String(chunkIndex));
        formData.append("expected_chunk_count", String(manifest.chunks.length));
        formData.append("expected_file_count", String(manifest.totalFiles));
        chunk.receipts.forEach((receipt) =>
          formData.append("staging_receipts", receipt),
        );
        try {
          const { data } = await apiClient.post<DocumentBatchReview>(
            API_ENDPOINTS.documents.upload(groupId, documentType),
            formData,
            {
              headers: { "Content-Type": "multipart/form-data" },
              timeout: 240_000,
              signal,
              onUploadProgress: (event) => reportUpload(event.loaded, event.total),
            },
          );
          return data;
        } catch (error) {
          if ((error as Partial<ApiError> | null)?.code === "HTTP_410") {
            throw new Error(
              "The secure PDF staging receipt expired. Select and check the PDFs again; "
              + "the browser did not retain raw file copies for fallback upload.",
            );
          }
          throw error;
        }
      },
    });
  },

  abortUpload: async (
    groupId: string,
    documentType: DistributionDocumentType,
    batchId: string,
  ): Promise<AbortDocumentUploadResult> => {
    const { data } = await apiClient.post<AbortDocumentUploadResult>(
      API_ENDPOINTS.documents.abortUpload(groupId, documentType, batchId),
    );
    return data;
  },

  reuploadPassengerDocument: async (
    groupId: string,
    documentType: DistributionDocumentType,
    passengerId: string,
    file: File,
  ): Promise<DocumentBatchReview> => {
    const formData = new FormData();
    formData.append("file", file);
    const { data } = await apiClient.post<DocumentBatchReview>(
      API_ENDPOINTS.documents.reupload(groupId, documentType, passengerId),
      formData,
      {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 60_000,
      },
    );
    return data;
  },

  deleteDocuments: async (
    groupId: string,
    documentType: DistributionDocumentType,
    documentIds: string[],
  ): Promise<DocumentBatchReview> => {
    const { data } = await apiClient.post<DocumentBatchReview>(API_ENDPOINTS.documents.deleteDocuments(groupId, documentType), {
      document_ids: documentIds,
    });
    return data;
  },

  unassignDocuments: async (
    groupId: string,
    documentType: DistributionDocumentType,
    documentIds: string[],
  ): Promise<DocumentBatchReview> => {
    const { data } = await apiClient.post<DocumentBatchReview>(
      API_ENDPOINTS.documents.unassignDocuments(groupId, documentType),
      {
        document_ids: documentIds,
      },
    );
    return data;
  },

  saveBatch: async (batchId: string): Promise<{ batch_id: string; status: string; saved_at: string }> => {
    const { data } = await apiClient.post<{ batch_id: string; status: string; saved_at: string }>(
      API_ENDPOINTS.documents.saveBatch(batchId),
    );
    return data;
  },

  previewWhatsAppDelivery: async (
    groupId: string,
    documentType: DistributionDocumentType,
  ): Promise<DocumentDeliveryPreview> => {
    const { data } = await apiClient.get<DocumentDeliveryPreview>(
      API_ENDPOINTS.documents.whatsappPreview(groupId, documentType),
    );
    return data;
  },

  sendWhatsAppDelivery: async (
    batchId: string,
    documentIds: string[],
    resendDocumentIds: string[],
    messageContent1: string,
    messageContent2: string,
  ): Promise<SendDocumentBroadcastResult> => {
    const { data } = await apiClient.post<SendDocumentBroadcastResult>(
      API_ENDPOINTS.documents.sendWhatsApp(batchId),
      {
        document_ids: documentIds,
        resend_document_ids: resendDocumentIds,
        message_content_1: messageContent1,
        message_content_2: messageContent2,
      },
    );
    return data;
  },

  getDeliveryTracking: async (groupId: string): Promise<DocumentDeliveryTracking> => {
    const { data } = await apiClient.get<DocumentDeliveryTracking>(
      API_ENDPOINTS.documents.deliveryTracking(groupId),
      { params: { limit: 6 } },
    );
    return data;
  },
};

function documentAssignmentFilename(
  groupName: string,
  documentType: DistributionDocumentType,
  filter: DocumentAssignmentExportFilter,
) {
  const raw = `${groupName}-${documentType}-${filter}-document-assignments`.trim();
  const safe = raw.replace(/[^A-Za-z0-9_.-]+/g, "_").slice(0, 120);
  return `${safe || "document"}.xlsx`;
}

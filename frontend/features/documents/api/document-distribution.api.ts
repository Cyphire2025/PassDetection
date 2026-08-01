import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
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
  createDocumentUploadSession,
  runChunkedDocumentUpload,
  type DocumentUploadProgress,
  type DocumentUploadSession,
} from "../services/document-upload-batching";

export const documentDistributionApi = {
  listGroups: async (): Promise<DocumentDistributionGroup[]> => {
    const { data } = await apiClient.get<DocumentDistributionGroup[]>(API_ENDPOINTS.documents.groups);
    return data;
  },

  getReview: async (groupId: string, documentType: DistributionDocumentType): Promise<DocumentBatchReview> => {
    const { data } = await apiClient.get<DocumentBatchReview>(API_ENDPOINTS.documents.review(groupId, documentType));
    return data;
  },

  verifyDocuments: async (
    groupId: string,
    documentType: DistributionDocumentType,
    files: File[],
    onProgress?: (progress: DocumentUploadProgress) => void,
  ): Promise<DocumentVerificationResult> => {
    const session = createDocumentUploadSession(files);
    const results: DocumentVerificationResult[] = [];
    await runChunkedDocumentUpload({
      session,
      onProgress,
      uploadChunk: async (chunk, _chunkIndex, reportUpload) => {
        const formData = new FormData();
        chunk.forEach((file) => formData.append("files", file));
        const { data } = await apiClient.post<DocumentVerificationResult>(
          API_ENDPOINTS.documents.verify(groupId, documentType),
          formData,
          {
            headers: { "Content-Type": "multipart/form-data" },
            timeout: 240_000,
            onUploadProgress: (event) => reportUpload(event.loaded, event.total),
          },
        );
        results.push(data);
        return data;
      },
    });
    return {
      group_id: groupId,
      document_type: documentType,
      total_count: results.reduce((total, result) => total + result.total_count, 0),
      accepted_count: results.reduce((total, result) => total + result.accepted_count, 0),
      rejected_count: results.reduce((total, result) => total + result.rejected_count, 0),
      files: results.flatMap((result) => result.files),
    };
  },

  uploadDocuments: async (
    groupId: string,
    documentType: DistributionDocumentType,
    files: File[],
    onProgress?: (progress: DocumentUploadProgress) => void,
    existingSession?: DocumentUploadSession,
  ): Promise<DocumentBatchReview> => {
    const session = existingSession ?? createDocumentUploadSession(files);
    return runChunkedDocumentUpload({
      session,
      onProgress,
      uploadChunk: async (chunk, chunkIndex, reportUpload) => {
        const formData = new FormData();
        formData.append("upload_id", session.uploadId);
        formData.append("chunk_id", session.chunkIds[chunkIndex]);
        formData.append("chunk_index", String(chunkIndex));
        formData.append("expected_chunk_count", String(session.chunks.length));
        formData.append("expected_file_count", String(session.totalFiles));
        chunk.forEach((file) => formData.append("files", file));
        const { data } = await apiClient.post<DocumentBatchReview>(
          API_ENDPOINTS.documents.upload(groupId, documentType),
          formData,
          {
            headers: { "Content-Type": "multipart/form-data" },
            timeout: 240_000,
            onUploadProgress: (event) => reportUpload(event.loaded, event.total),
          },
        );
        return data;
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
    );
    return data;
  },
};

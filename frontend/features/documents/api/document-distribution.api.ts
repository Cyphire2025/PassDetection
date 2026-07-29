import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  DistributionDocumentType,
  DocumentBatchReview,
  DocumentDistributionGroup,
  DocumentDeliveryPreview,
  DocumentDeliveryTracking,
  DocumentVerificationResult,
  SendDocumentBroadcastResult,
} from "@/types/document-distribution.types";

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
  ): Promise<DocumentVerificationResult> => {
    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));
    const { data } = await apiClient.post<DocumentVerificationResult>(API_ENDPOINTS.documents.verify(groupId, documentType), formData, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 60_000,
    });
    return data;
  },

  uploadDocuments: async (
    groupId: string,
    documentType: DistributionDocumentType,
    files: File[],
    onProgress?: (progress: number) => void,
  ): Promise<DocumentBatchReview> => {
    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));
    const { data } = await apiClient.post<DocumentBatchReview>(API_ENDPOINTS.documents.upload(groupId, documentType), formData, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 120_000,
      onUploadProgress: (event) => {
        if (!event.total) return;
        onProgress?.(Math.round((event.loaded / event.total) * 100));
      },
    });
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
    messageContent1: string,
    messageContent2: string,
  ): Promise<SendDocumentBroadcastResult> => {
    const { data } = await apiClient.post<SendDocumentBroadcastResult>(
      API_ENDPOINTS.documents.sendWhatsApp(batchId),
      {
        document_ids: documentIds,
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

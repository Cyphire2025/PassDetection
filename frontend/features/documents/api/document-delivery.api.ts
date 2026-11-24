import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  DistributionDocumentType,
  DocumentDeliveryPreview,
  DocumentDeliveryTracking,
  SendDocumentBroadcastResult
} from "@/types/document-distribution.types";

export const documentDeliveryApi = {
  previewWhatsAppDelivery: async (
    groupId: string,
    documentType: DistributionDocumentType,
    signal?: AbortSignal,
    broadcastGroupId?: string,
  ): Promise<DocumentDeliveryPreview> => {
    const { data } = await apiClient.get<DocumentDeliveryPreview>(
      API_ENDPOINTS.documents.whatsappPreview(groupId, documentType),
      { signal, params: broadcastGroupId ? { broadcast_group_id: broadcastGroupId } : undefined },
    );
    return data;
  },

  sendWhatsAppDelivery: async (
    batchId: string,
    documentIds: string[],
    resendDocumentIds: string[],
    messageContent1: string,
    messageContent2: string,
    previewToken: string,
    broadcastGroupId?: string,
  ): Promise<SendDocumentBroadcastResult> => {
    const { data } = await apiClient.post<SendDocumentBroadcastResult>(
      API_ENDPOINTS.documents.sendWhatsApp(batchId),
      {
        document_ids: documentIds,
        resend_document_ids: resendDocumentIds,
        message_content_1: messageContent1,
        message_content_2: messageContent2,
        preview_token: previewToken,
        broadcast_group_id: broadcastGroupId,
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

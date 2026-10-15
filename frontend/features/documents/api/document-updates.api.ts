import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { DistributionDocumentType } from "@/types/document-distribution.types";

export interface DocumentUpdateRecipient {
  passenger_id: string;
  passenger_name: string;
  phone_number: string | null;
  recipient_id: string | null;
  broadcast_group_id: string | null;
  document_count: number;
  confirmed_count: number;
  eligible: boolean;
  reason: string | null;
  latest_update_status: string | null;
  latest_update_error?: string | null;
  latest_update_at?: string | null;
}

export interface DocumentUpdatePreview {
  group_id: string;
  document_type: DistributionDocumentType;
  preview_token: string;
  template_name: string;
  template_language: string;
  can_send: boolean;
  configuration_error: string | null;
  recipients: DocumentUpdateRecipient[];
}

export interface DocumentUpdateRequest {
  request_id: string;
  preview_token: string;
  passenger_ids: string[];
  message_content: string;
  broadcast_group_id?: string;
}

export interface DocumentUpdateResult {
  request_id: string;
  queued_count: number;
  passenger_count: number;
  message: string;
}

export const documentUpdatesApi = {
  async preview(groupId: string, documentType: DistributionDocumentType, broadcastGroupId?: string, signal?: AbortSignal) {
    return (await apiClient.get<DocumentUpdatePreview>(
      `${API_ENDPOINTS.documents.review(groupId, documentType)}/update-preview`,
      { params: broadcastGroupId ? { broadcast_group_id: broadcastGroupId } : undefined, signal },
    )).data;
  },
  async send(groupId: string, documentType: DistributionDocumentType, request: DocumentUpdateRequest) {
    return (await apiClient.post<DocumentUpdateResult>(
      `${API_ENDPOINTS.documents.review(groupId, documentType)}/send-update`, request,
    )).data;
  },
};

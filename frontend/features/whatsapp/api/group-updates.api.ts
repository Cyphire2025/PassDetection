import apiClient from "@/lib/api/client";
import type { DistributionDocumentType } from "@/types/document-distribution.types";
import type { DocumentUpdateResult } from "@/features/documents/api/document-updates.api";

export interface GroupUpdateAudience {
  submission_status: "all" | "submitted" | "not_submitted";
  document_status: "all" | "sent" | "pending";
  document_type: DistributionDocumentType;
}
export interface GroupUpdateRecipient {
  audience_key: string;
  name: string;
  recipient_id: string;
  broadcast_group_id: string;
  passenger_id: string | null;
  phone_number: string | null;
  phone_source: "submitted" | "imported";
  submission_status: "submitted" | "not_submitted" | "needs_review";
  document_count: number;
  confirmed_count: number;
  eligible: boolean;
  reason: string | null;
  latest_update_status: string | null;
  latest_update_at: string | null;
}
export interface GroupUpdatePreview {
  group_id: string;
  audience: GroupUpdateAudience;
  preview_token: string;
  template_name: string;
  template_language: string;
  can_send: boolean;
  configuration_error: string | null;
  recipients: GroupUpdateRecipient[];
}
export interface GroupUpdateRequest {
  request_id: string;
  preview_token: string;
  audience: GroupUpdateAudience;
  audience_keys: string[];
  message_content: string;
}
const path = (groupId: string) => `/api/v1/document-distribution/groups/${groupId}/updates`;
export const groupUpdatesApi = {
  async preview(groupId: string, audience: GroupUpdateAudience, signal?: AbortSignal) {
    return (await apiClient.post<GroupUpdatePreview>(`${path(groupId)}/preview`, audience, { signal })).data;
  },
  async send(groupId: string, request: GroupUpdateRequest) {
    return (await apiClient.post<DocumentUpdateResult>(`${path(groupId)}/send`, request)).data;
  },
};

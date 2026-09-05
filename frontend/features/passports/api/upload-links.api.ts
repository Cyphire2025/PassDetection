/**
 * Upload Links API
 * =================
 * Handles API calls for creating, listing, and revoking client upload links.
 */

import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { PublicFlowTelemetryPayload } from "@/features/upload/services/public-flow-telemetry";
import { getOrCreatePublicUploadSessionId } from "./public-upload-session";
import type { UploadConfiguration } from "../types/upload-configuration";

const publicUploadHeaders = (token: string) => ({
  "X-Upload-Session-ID": getOrCreatePublicUploadSessionId(token),
});

export interface CustomUploadQuestion {
  id: string;
  label: string;
  options: string[];
  enabled: boolean;
  required?: boolean;
}

export interface CustomUploadDetail {
  id: string;
  label: string;
  enabled: boolean;
  required?: boolean;
}

export interface UpdateUploadLinkRequest {
  name: string;
  destination?: string | null;
  travel_date?: string | null;
  return_date?: string | null;
  timezone?: string;
  package_name?: string | null;
  departure_cities?: string[];
  base_city_enabled: boolean;
  nearest_international_airport_enabled: boolean;
  staff_code_enabled: boolean;
  agent_employee_code_enabled: boolean;
  meal_preference_enabled: boolean;
  require_selfie: boolean;
  allow_files_from_device: boolean;
  ask_nearest_domestic_airport: boolean;
  relation_with_qualifier_enabled: boolean;
  designation_enabled: boolean;
  agency_dealership_name_enabled: boolean;
  upload_configuration?: UploadConfiguration;
  custom_questions?: CustomUploadQuestion[];
  custom_details?: CustomUploadDetail[];
  whatsapp_broadcast_group_ids?: string[];
  notes?: string | null;
}

export interface CreateUploadLinkRequest extends UpdateUploadLinkRequest {
  destination: string;
  travel_date: string;
  return_date: string;
  timezone: string;
  custom_questions: CustomUploadQuestion[];
  custom_details: CustomUploadDetail[];
}

export interface LinkedWhatsAppBroadcast {
  id: string;
  name: string;
  recipient_count: number;
  created_at: string;
  updated_at: string;
}

export interface GroupWhatsAppLinksResponse {
  client_group_id: string;
  broadcasts: LinkedWhatsAppBroadcast[];
  broadcast_count: number;
  recipient_count: number;
  can_manage: boolean;
}

export type GroupWhatsAppMatchStatus =
  | "submitted"
  | "not_submitted"
  | "multiple_submissions"
  | "needs_review"
  | "unmatched_submission"
  | "replacement"
  | "rejected_upload";

export interface GroupWhatsAppMatchCounts {
  total_recipients: number;
  submitted_count: number;
  not_submitted_count: number;
  multiple_submission_count: number;
  matched_submission_count: number;
  needs_review_count: number;
  needs_review_submission_count: number;
  unmatched_submission_count: number;
  replacement_count: number;
  rejected_upload_count: number;
}

export interface GroupWhatsAppMatchEvidence {
  submission_id: string;
  kind:
    | "phone"
    | "email"
    | "passport_number"
    | "staff_code"
    | "entered_name"
    | "passport_name";
  recipient_value: string;
  submission_value: string;
  weight: number;
}

export interface GroupWhatsAppRecipientFields {
  recipient_id: string;
  fields: Record<string, string>;
}

export interface GroupWhatsAppSubmissionDetail {
  submission_id: string;
  name: string;
  phone: string | null;
  email: string | null;
  fields: Record<string, unknown>;
}

export interface GroupWhatsAppMatch {
  status: GroupWhatsAppMatchStatus;
  match_basis: string | null;
  normalized_phone: string | null;
  recipient_ids: string[];
  submission_ids: string[];
  broadcast_ids: string[];
  broadcast_names: string[];
  recipient_names: string[];
  submission_names: string[];
  confidence: "high" | "medium" | "none";
  match_evidence: GroupWhatsAppMatchEvidence[];
  candidate_submission_ids: string[];
  recipient_fields: GroupWhatsAppRecipientFields[];
  submission_details: GroupWhatsAppSubmissionDetail[];
  resolution_id: string | null;
  updated_at: string | null;
}

export interface GroupWhatsAppMatchesResponse {
  client_group_id: string;
  selected_broadcast_id: string | null;
  linked_broadcast_count: number;
  counts: GroupWhatsAppMatchCounts;
  matches: GroupWhatsAppMatch[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface GroupWhatsAppMatchesParams {
  status?: "all" | GroupWhatsAppMatchStatus;
  broadcast_id?: string;
  sort_by?: "name" | "phone" | "status" | "broadcast" | "updated_at";
  sort_order?: "asc" | "desc";
  page?: number;
  page_size?: number;
}

export interface ReplacementCandidate {
  recipient_id: string;
  recipient_ids: string[];
  name: string | null;
  phone: string;
  broadcast_ids: string[];
  broadcast_names: string[];
  imported_fields: Record<string, string>;
}

export interface ReplacementCandidateListResponse {
  client_group_id: string;
  items: ReplacementCandidate[];
}

export interface PassportRosterResolution {
  id: string;
  client_group_id: string;
  submission_id: string;
  resolution_type: "replacement" | "rejected";
  status: "active" | "restored";
  broadcast_recipient_id: string | null;
  suppressed_recipient_ids: string[];
  excluded_submission_ids: string[];
  created_at: string;
  restored_at: string | null;
}

export interface QualifierRelationOption {
  code: string;
  label: string;
}

export interface UploadLinkResponse {
  id: string;
  name: string;
  token: string;
  agency_id: string;
  status: "active" | "closed" | "archived" | "deleted";
  created_by_user_id: string | null;
  created_at: string;
  closed_at: string | null;
  destination: string | null;
  travel_date: string | null;
  return_date: string | null;
  timezone: string;
  package_name: string | null;
  departure_cities: string[];
  base_city_enabled: boolean;
  nearest_international_airport_enabled: boolean;
  staff_code_enabled: boolean;
  agent_employee_code_enabled: boolean;
  meal_preference_enabled: boolean;
  require_selfie: boolean;
  allow_files_from_device: boolean;
  ask_nearest_domestic_airport: boolean;
  relation_with_qualifier_enabled: boolean;
  designation_enabled: boolean;
  agency_dealership_name_enabled: boolean;
  upload_configuration?: UploadConfiguration | null;
  custom_questions: CustomUploadQuestion[];
  custom_details: CustomUploadDetail[];
  qualifier_relation_options: QualifierRelationOption[];
  notes: string | null;
  deleted_at: string | null;
  deleted_passport_count: number;
  deletion_retained_records: boolean;
}

export const uploadLinksApi = {
  create: async (data: CreateUploadLinkRequest): Promise<UploadLinkResponse> => {
    const response = await apiClient.post<UploadLinkResponse>(API_ENDPOINTS.uploadLinks.root, data);
    return response.data;
  },

  list: async (statusFilter?: UploadLinkResponse["status"]): Promise<UploadLinkResponse[]> => {
    const response = await apiClient.get<UploadLinkResponse[]>(API_ENDPOINTS.uploadLinks.root, {
      params: statusFilter ? { status_filter: statusFilter } : undefined,
    });
    return response.data;
  },

  revoke: async (id: string): Promise<UploadLinkResponse> => {
    const response = await apiClient.post<UploadLinkResponse>(API_ENDPOINTS.uploadLinks.revoke(id));
    return response.data;
  },

  delete: async (id: string): Promise<UploadLinkResponse> => {
    const response = await apiClient.delete<UploadLinkResponse>(API_ENDPOINTS.uploadLinks.delete(id));
    return response.data;
  },

  update: async (id: string, data: UpdateUploadLinkRequest): Promise<UploadLinkResponse> => {
    const response = await apiClient.patch<UploadLinkResponse>(API_ENDPOINTS.uploadLinks.detail(id), data);
    return response.data;
  },

  getWhatsAppLinks: async (id: string): Promise<GroupWhatsAppLinksResponse> => {
    const response = await apiClient.get<GroupWhatsAppLinksResponse>(
      API_ENDPOINTS.uploadLinks.whatsappLinks(id),
    );
    return response.data;
  },

  updateWhatsAppLinks: async (
    id: string,
    whatsappBroadcastGroupIds: string[],
  ): Promise<GroupWhatsAppLinksResponse> => {
    const response = await apiClient.put<GroupWhatsAppLinksResponse>(
      API_ENDPOINTS.uploadLinks.whatsappLinks(id),
      { whatsapp_broadcast_group_ids: whatsappBroadcastGroupIds },
    );
    return response.data;
  },

  getWhatsAppBroadcastOptions: async (
    id?: string,
  ): Promise<LinkedWhatsAppBroadcast[]> => {
    const response = await apiClient.get<LinkedWhatsAppBroadcast[]>(
      id
        ? API_ENDPOINTS.uploadLinks.groupWhatsAppBroadcastOptions(id)
        : API_ENDPOINTS.uploadLinks.whatsappBroadcastOptions,
    );
    return response.data;
  },

  getWhatsAppMatches: async (
    id: string,
    params: GroupWhatsAppMatchesParams = {},
  ): Promise<GroupWhatsAppMatchesResponse> => {
    const response = await apiClient.get<GroupWhatsAppMatchesResponse>(
      API_ENDPOINTS.uploadLinks.whatsappMatches(id),
      { params },
    );
    return response.data;
  },

  getReplacementCandidates: async (
    id: string,
  ): Promise<ReplacementCandidateListResponse> => {
    const response = await apiClient.get<ReplacementCandidateListResponse>(
      API_ENDPOINTS.uploadLinks.replacementCandidates(id),
    );
    return response.data;
  },

  resolveUnidentifiedReplacement: async (
    id: string,
    submissionId: string,
    recipientId: string,
    requestId: string,
  ): Promise<PassportRosterResolution> => {
    const response = await apiClient.post<PassportRosterResolution>(
      API_ENDPOINTS.uploadLinks.resolveUnidentifiedReplacement(id, submissionId),
      { recipient_id: recipientId, request_id: requestId },
    );
    return response.data;
  },

  rejectUnidentifiedUpload: async (
    id: string,
    submissionId: string,
    requestId: string,
  ): Promise<PassportRosterResolution> => {
    const response = await apiClient.post<PassportRosterResolution>(
      API_ENDPOINTS.uploadLinks.rejectUnidentifiedUpload(id, submissionId),
      { request_id: requestId },
    );
    return response.data;
  },

  restoreRosterResolution: async (
    id: string,
    resolutionId: string,
  ): Promise<PassportRosterResolution> => {
    const response = await apiClient.post<PassportRosterResolution>(
      API_ENDPOINTS.uploadLinks.restoreRosterResolution(id, resolutionId),
    );
    return response.data;
  },

  permanentDelete: async (id: string, retainRecords: boolean): Promise<void> => {
    await apiClient.delete(API_ENDPOINTS.uploadLinks.permanentDelete(id), {
      params: { retain_records: retainRecords },
    });
  },

  restore: async (id: string): Promise<UploadLinkResponse> => {
    const response = await apiClient.post<UploadLinkResponse>(API_ENDPOINTS.uploadLinks.restore(id));
    return response.data;
  },

  getByToken: async (token: string): Promise<UploadLinkResponse> => {
    const response = await apiClient.get<UploadLinkResponse>(
      API_ENDPOINTS.uploadLinks.byToken(token),
      { headers: publicUploadHeaders(token) },
    );
    return response.data;
  },

  recordTelemetry: async (
    token: string,
    payload: PublicFlowTelemetryPayload,
    signal?: AbortSignal,
  ): Promise<void> => {
    await apiClient.post(
      API_ENDPOINTS.uploadLinks.telemetry(token),
      payload,
      {
        headers: publicUploadHeaders(token),
        signal,
      },
    );
  },

  recordTelemetryKeepalive: (
    token: string,
    payload: PublicFlowTelemetryPayload,
  ): Promise<Response> => fetch(
    API_ENDPOINTS.uploadLinks.telemetry(token),
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...publicUploadHeaders(token),
      },
      body: JSON.stringify(payload),
      credentials: "same-origin",
      cache: "no-store",
      keepalive: true,
    },
  ),

  createQualifierSelection: async (
    token: string,
    choice: { is_self: boolean; relation_code: string | null },
  ): Promise<QualifierSelectionState & { selection_token: string }> => {
    const response = await apiClient.post<QualifierSelectionState & { selection_token: string }>(
      API_ENDPOINTS.uploadLinks.qualifierSelection(token),
      choice,
      { headers: publicUploadHeaders(token) },
    );
    return response.data;
  },

  getQualifierSelection: async (
    token: string,
    selectionToken: string,
  ): Promise<QualifierSelectionState> => {
    const response = await apiClient.get<QualifierSelectionState>(
      API_ENDPOINTS.uploadLinks.qualifierSelection(token),
      {
        headers: {
          ...publicUploadHeaders(token),
          "X-Qualifier-Selection-Token": selectionToken,
        },
      },
    );
    return response.data;
  },
};

export interface QualifierSelectionState {
  is_self: boolean;
  relation_code: string | null;
  relation_label: string;
  selected_at: string;
  expires_at: string;
  status: "active" | "expired" | "consumed";
  submission_id: string | null;
}

/**
 * Upload Links API
 * =================
 * Handles API calls for creating, listing, and revoking client upload links.
 */

import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { PublicFlowTelemetryPayload } from "@/features/upload/services/public-flow-telemetry";
import { getOrCreatePublicUploadSessionId } from "./public-upload-session";

const publicUploadHeaders = (token: string) => ({
  "X-Upload-Session-ID": getOrCreatePublicUploadSessionId(token),
});

export interface CreateUploadLinkRequest {
  name: string;
  destination?: string | null;
  travel_date?: string | null;
  return_date?: string | null;
  package_name?: string | null;
  departure_cities?: string[];
  base_city_enabled: boolean;
  nearest_international_airport_enabled: boolean;
  staff_code_enabled: boolean;
  meal_preference_enabled: boolean;
  require_selfie: boolean;
  allow_files_from_device: boolean;
  ask_nearest_domestic_airport: boolean;
  relation_with_qualifier_enabled: boolean;
  whatsapp_broadcast_group_ids?: string[];
  notes?: string | null;
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
  | "multiple_submissions";

export interface GroupWhatsAppMatchCounts {
  total_recipients: number;
  submitted_count: number;
  not_submitted_count: number;
  multiple_submission_count: number;
  matched_submission_count: number;
}

export interface GroupWhatsAppMatch {
  status: GroupWhatsAppMatchStatus;
  match_basis: "phone" | null;
  normalized_phone: string | null;
  recipient_ids: string[];
  submission_ids: string[];
  broadcast_ids: string[];
  broadcast_names: string[];
  recipient_names: string[];
  submission_names: string[];
  updated_at: string | null;
}

export interface GroupWhatsAppMatchesResponse {
  client_group_id: string;
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
  sort_by?: "name" | "phone" | "status" | "broadcast" | "updated_at";
  sort_order?: "asc" | "desc";
  page?: number;
  page_size?: number;
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
  package_name: string | null;
  departure_cities: string[];
  base_city_enabled: boolean;
  nearest_international_airport_enabled: boolean;
  staff_code_enabled: boolean;
  meal_preference_enabled: boolean;
  require_selfie: boolean;
  allow_files_from_device: boolean;
  ask_nearest_domestic_airport: boolean;
  relation_with_qualifier_enabled: boolean;
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

  update: async (id: string, data: CreateUploadLinkRequest): Promise<UploadLinkResponse> => {
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

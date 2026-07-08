/**
 * Upload Links API
 * =================
 * Handles API calls for creating, listing, and revoking client upload links.
 */

import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";

export interface CreateUploadLinkRequest {
  name: string;
  destination?: string | null;
  travel_date?: string | null;
  return_date?: string | null;
  package_name?: string | null;
  notes?: string | null;
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
    const response = await apiClient.get<UploadLinkResponse>(API_ENDPOINTS.uploadLinks.byToken(token));
    return response.data;
  },
};

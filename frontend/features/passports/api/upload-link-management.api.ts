import type { PassportRequestConfig } from "./passport-request-config";
import { optionalRequestConfig, optionalBodylessRequestConfig } from "./passport-request-config";
import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  UpdateUploadLinkRequest,
  CreateUploadLinkRequest,
  UploadLinkResponse,
} from "./upload-link.types";

export const uploadLinkManagementApi = {
  assignCompany: async (group: UploadLinkResponse, companyId: string): Promise<UploadLinkResponse> => {
    const response = await apiClient.patch<UploadLinkResponse>(API_ENDPOINTS.companies.assignment(group.id), {
      company_id: companyId, expected_revision: group.company_revision ?? 0,
    }, { params: { agency_id: group.agency_id } });
    return response.data;
  },

  create: async (data: CreateUploadLinkRequest, requestConfig?: PassportRequestConfig): Promise<UploadLinkResponse> => {
    const response = await apiClient.post<UploadLinkResponse>(API_ENDPOINTS.uploadLinks.root, data, ...optionalRequestConfig(requestConfig));
    return response.data;
  },

  list: async (statusFilter?: UploadLinkResponse["status"]): Promise<UploadLinkResponse[]> => {
    const response = await apiClient.get<UploadLinkResponse[]>(API_ENDPOINTS.uploadLinks.root, {
      params: statusFilter ? { status_filter: statusFilter } : undefined,
    });
    return response.data;
  },

  revoke: async (id: string, requestConfig?: PassportRequestConfig): Promise<UploadLinkResponse> => {
    const response = await apiClient.post<UploadLinkResponse>(API_ENDPOINTS.uploadLinks.revoke(id), ...optionalBodylessRequestConfig(requestConfig));
    return response.data;
  },

  delete: async (id: string, requestConfig?: PassportRequestConfig): Promise<UploadLinkResponse> => {
    const response = await apiClient.delete<UploadLinkResponse>(API_ENDPOINTS.uploadLinks.delete(id), ...optionalRequestConfig(requestConfig));
    return response.data;
  },

  update: async (id: string, data: UpdateUploadLinkRequest, requestConfig?: PassportRequestConfig): Promise<UploadLinkResponse> => {
    const response = await apiClient.patch<UploadLinkResponse>(API_ENDPOINTS.uploadLinks.detail(id), data, ...optionalRequestConfig(requestConfig));
    return response.data;
  },

  permanentDelete: async (id: string, retainRecords: boolean, requestConfig?: PassportRequestConfig): Promise<void> => {
    await apiClient.delete(API_ENDPOINTS.uploadLinks.permanentDelete(id), { ...requestConfig,
      params: { retain_records: retainRecords },
    });
  },

  restore: async (id: string, requestConfig?: PassportRequestConfig): Promise<UploadLinkResponse> => {
    const response = await apiClient.post<UploadLinkResponse>(API_ENDPOINTS.uploadLinks.restore(id), ...optionalBodylessRequestConfig(requestConfig));
    return response.data;
  },
};

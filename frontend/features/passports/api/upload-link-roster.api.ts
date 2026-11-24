import type { PassportRequestConfig } from "./passport-request-config";
import { optionalRequestConfig, optionalBodylessRequestConfig } from "./passport-request-config";
import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  LinkedWhatsAppBroadcast,
  GroupWhatsAppLinksResponse,
  GroupWhatsAppMatchesResponse,
  GroupWhatsAppMatchesParams,
  ReplacementCandidateListResponse,
  PassportRosterResolution,
} from "./upload-link.types";

export const uploadLinkRosterApi = {
  getWhatsAppLinks: async (id: string): Promise<GroupWhatsAppLinksResponse> => {
    const response = await apiClient.get<GroupWhatsAppLinksResponse>(
      API_ENDPOINTS.uploadLinks.whatsappLinks(id),
    );
    return response.data;
  },

  updateWhatsAppLinks: async (
    id: string,
    whatsappBroadcastGroupIds: string[],
    matchingFieldsByBroadcast?: Record<string, string[]>, requestConfig?: PassportRequestConfig
  ): Promise<GroupWhatsAppLinksResponse> => {
    const response = await apiClient.put<GroupWhatsAppLinksResponse>(
      API_ENDPOINTS.uploadLinks.whatsappLinks(id),
      {
        whatsapp_broadcast_group_ids: whatsappBroadcastGroupIds,
        ...(matchingFieldsByBroadcast
          ? { matching_fields_by_broadcast: matchingFieldsByBroadcast }
          : {}),
      }, ...optionalRequestConfig(requestConfig)
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
    requestId: string, requestConfig?: PassportRequestConfig
  ): Promise<PassportRosterResolution> => {
    const response = await apiClient.post<PassportRosterResolution>(
      API_ENDPOINTS.uploadLinks.resolveUnidentifiedReplacement(id, submissionId),
      { recipient_id: recipientId, request_id: requestId }, ...optionalRequestConfig(requestConfig)
    );
    return response.data;
  },

  rejectUnidentifiedUpload: async (
    id: string,
    submissionId: string,
    requestId: string, requestConfig?: PassportRequestConfig
  ): Promise<PassportRosterResolution> => {
    const response = await apiClient.post<PassportRosterResolution>(
      API_ENDPOINTS.uploadLinks.rejectUnidentifiedUpload(id, submissionId),
      { request_id: requestId }, ...optionalRequestConfig(requestConfig)
    );
    return response.data;
  },

  restoreRosterResolution: async (
    id: string,
    resolutionId: string, requestConfig?: PassportRequestConfig
  ): Promise<PassportRosterResolution> => {
    const response = await apiClient.post<PassportRosterResolution>(
      API_ENDPOINTS.uploadLinks.restoreRosterResolution(id, resolutionId), ...optionalBodylessRequestConfig(requestConfig)
    );
    return response.data;
  },
};

import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  SendTravellerWelcomeRequest,
  SendTravellerWelcomeResult,
  TravellerWelcomePreview,
} from "@/types/document-distribution.types";

export const travellerWelcomeApi = {
  preview: async (
    groupId: string,
    sourceBroadcastId?: string,
    headerImageId?: string,
    signal?: AbortSignal,
  ): Promise<TravellerWelcomePreview> => {
    const { data } = await apiClient.get<TravellerWelcomePreview>(
      API_ENDPOINTS.documents.travellerWelcomePreview(groupId),
      { params: { source_broadcast_id: sourceBroadcastId, header_image_id: headerImageId }, signal },
    );
    return data;
  },
  send: async (
    groupId: string,
    request: SendTravellerWelcomeRequest,
  ): Promise<SendTravellerWelcomeResult> => {
    const { data } = await apiClient.post<SendTravellerWelcomeResult>(
      API_ENDPOINTS.documents.travellerWelcomeSend(groupId),
      request,
    );
    return data;
  },
};

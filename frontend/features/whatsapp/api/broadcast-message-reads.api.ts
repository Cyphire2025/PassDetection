import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { WhatsAppMessageDraft, WhatsAppPreviewResponse } from "../types/messages";

export const whatsappMessageReadsApi = {
  previewMessage: async (
    groupId: string,
    draft: WhatsAppMessageDraft,
    signal?: AbortSignal,
  ): Promise<WhatsAppPreviewResponse> => {
    const { data } = await apiClient.post<WhatsAppPreviewResponse>(
      API_ENDPOINTS.whatsapp.preview(groupId),
      draft,
      { signal },
    );
    return data;
  }
};

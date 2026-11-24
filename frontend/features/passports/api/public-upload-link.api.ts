import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { PublicFlowTelemetryPayload } from "@/features/upload/services/public-flow-telemetry";
import { getOrCreatePublicUploadSessionId } from "./public-upload-session";
import type { UploadLinkResponse, QualifierSelectionState } from "./upload-link.types";

const publicUploadHeaders = (token: string) => ({
  "X-Upload-Session-ID": getOrCreatePublicUploadSessionId(token),
});
export const publicUploadLinkApi = {
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
    choice: { is_self: boolean; relation_code: string | null; other_relation?: string },
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
    signal?: AbortSignal,
  ): Promise<QualifierSelectionState> => {
    const response = await apiClient.get<QualifierSelectionState>(
      API_ENDPOINTS.uploadLinks.qualifierSelection(token),
      {
        signal,
        headers: {
          ...publicUploadHeaders(token),
          "X-Qualifier-Selection-Token": selectionToken,
        },
      },
    );
    return response.data;
  },
};

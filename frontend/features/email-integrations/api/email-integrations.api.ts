import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  EmailActivityItem,
  EmailAuthorizationResponse,
  EmailConnection,
  EmailConnectionActionResponse,
  EmailIntegrationStatus,
  EmailIntegrationSummary,
  EmailMessageDetail,
  EmailReviewActionResponse,
  EmailReviewItem,
  EmailReviewOptions,
  ResolveEmailReviewRequest,
} from "../types";
import { normalizeEmailCollection } from "../utils/email-integrations";

type CollectionResponse<T> = T[] | { items: T[] };

export const emailIntegrationsApi = {
  status: async (): Promise<EmailIntegrationStatus> => {
    const { data } = await apiClient.get<EmailIntegrationStatus>(
      API_ENDPOINTS.emailIntegrations.status,
    );
    return data;
  },

  connections: async (): Promise<EmailConnection[]> => {
    const { data } = await apiClient.get<CollectionResponse<EmailConnection>>(
      API_ENDPOINTS.emailIntegrations.connections,
    );
    return normalizeEmailCollection(data);
  },

  authorizeGmail: async (
    connectionId?: string,
  ): Promise<EmailAuthorizationResponse> => {
    const { data } = await apiClient.post<EmailAuthorizationResponse>(
      API_ENDPOINTS.emailIntegrations.gmailAuthorize,
      connectionId ? { connection_id: connectionId } : {},
    );
    return data;
  },

  syncConnection: async (
    connectionId: string,
  ): Promise<EmailConnectionActionResponse> => {
    const { data } = await apiClient.post<EmailConnectionActionResponse>(
      API_ENDPOINTS.emailIntegrations.connectionSync(connectionId),
    );
    return data;
  },

  pauseConnection: async (
    connectionId: string,
  ): Promise<EmailConnectionActionResponse> => {
    const { data } = await apiClient.post<EmailConnectionActionResponse>(
      API_ENDPOINTS.emailIntegrations.connectionPause(connectionId),
    );
    return data;
  },

  resumeConnection: async (
    connectionId: string,
  ): Promise<EmailConnectionActionResponse> => {
    const { data } = await apiClient.post<EmailConnectionActionResponse>(
      API_ENDPOINTS.emailIntegrations.connectionResume(connectionId),
    );
    return data;
  },

  disconnectConnection: async (connectionId: string): Promise<void> => {
    await apiClient.delete(
      API_ENDPOINTS.emailIntegrations.connection(connectionId),
    );
  },

  summary: async (): Promise<EmailIntegrationSummary> => {
    const { data } = await apiClient.get<EmailIntegrationSummary>(
      API_ENDPOINTS.emailIntegrations.summary,
    );
    return data;
  },

  reviews: async (status: string): Promise<EmailReviewItem[]> => {
    const { data } = await apiClient.get<CollectionResponse<EmailReviewItem>>(
      API_ENDPOINTS.emailIntegrations.reviews,
      { params: { status } },
    );
    return normalizeEmailCollection(data);
  },

  reviewOptions: async (
    groupId?: string,
  ): Promise<EmailReviewOptions> => {
    const { data } = await apiClient.get<EmailReviewOptions>(
      API_ENDPOINTS.emailIntegrations.reviewOptions,
      { params: groupId ? { group_id: groupId } : undefined },
    );
    return data;
  },

  resolveReview: async ({
    reviewId,
    request,
  }: {
    reviewId: string;
    request: ResolveEmailReviewRequest;
  }): Promise<EmailReviewActionResponse> => {
    const { data } = await apiClient.post<EmailReviewActionResponse>(
      API_ENDPOINTS.emailIntegrations.resolveReview(reviewId),
      request,
    );
    return data;
  },

  activity: async (): Promise<EmailActivityItem[]> => {
    const { data } = await apiClient.get<CollectionResponse<EmailActivityItem>>(
      API_ENDPOINTS.emailIntegrations.activity,
    );
    return normalizeEmailCollection(data);
  },

  message: async (messageId: string): Promise<EmailMessageDetail> => {
    const { data } = await apiClient.get<EmailMessageDetail>(
      API_ENDPOINTS.emailIntegrations.message(messageId),
    );
    return data;
  },
};

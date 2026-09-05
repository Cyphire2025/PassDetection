import apiClient, { type ApiError } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  DecideEmailDeadlineRequest,
  DecideEmailDraftRequest,
  DecideEmailProposalRequest,
  EmailActivityItem,
  EmailAiConnectionSettingsResponse,
  EmailAiFeedbackRequest,
  EmailAiFeedbackResponse,
  EmailAiRetryResponse,
  EmailAiRolloutScope,
  EmailAiRolloutTarget,
  EmailAiRolloutTargetsResponse,
  EmailAuthorizationResponse,
  EmailConnection,
  EmailConnectionActionResponse,
  EmailInboxDeadline,
  EmailInboxDraft,
  EmailIntegrationStatus,
  EmailIntegrationSummary,
  EmailIntelligenceDetail,
  EmailMessageDetail,
  EmailOperationalInboxResponse,
  EmailOperationalInboxView,
  EmailProposalDecisionResponse,
  EmailReviewActionResponse,
  EmailReviewItem,
  EmailReviewOptions,
  RemoveEmailConnectionResponse,
  ResolveEmailReviewRequest,
  UpdateEmailAiRolloutPolicyRequest,
  UpdateEmailReplyDraftRequest,
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

  authorize: async (
    provider: "gmail" | "outlook",
    connectionId?: string,
  ): Promise<EmailAuthorizationResponse> => {
    const { data } = await apiClient.post<EmailAuthorizationResponse>(
      provider === "outlook"
        ? API_ENDPOINTS.emailIntegrations.outlookAuthorize
        : API_ENDPOINTS.emailIntegrations.gmailAuthorize,
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

  updateAiSettings: async ({
    connectionId,
    enabled,
  }: {
    connectionId: string;
    enabled: boolean;
  }): Promise<EmailAiConnectionSettingsResponse> => {
    const { data } = await apiClient.put<EmailAiConnectionSettingsResponse>(
      API_ENDPOINTS.emailIntegrations.connectionAiSettings(connectionId),
      { enabled },
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

  removeConnection: async ({
    connectionId,
    confirmationEmail,
  }: {
    connectionId: string;
    confirmationEmail: string;
  }): Promise<RemoveEmailConnectionResponse> => {
    const { data } = await apiClient.delete<RemoveEmailConnectionResponse>(
      API_ENDPOINTS.emailIntegrations.connectionData(connectionId),
      { data: { confirmation_email: confirmationEmail } },
    );
    return data;
  },

  inbox: async ({
    view,
    limit = 20,
    cursor,
    signal,
  }: {
    view: EmailOperationalInboxView;
    limit?: number;
    cursor?: string;
    signal?: AbortSignal;
  }): Promise<EmailOperationalInboxResponse> => {
    const { data } = await apiClient.get<EmailOperationalInboxResponse>(
      API_ENDPOINTS.emailIntegrations.inbox,
      {
        signal,
        params: {
          view,
          limit,
          cursor,
        },
      },
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
    messageId?: string,
  ): Promise<EmailReviewOptions> => {
    const params = {
      ...(groupId ? { group_id: groupId } : {}),
      ...(messageId ? { message_id: messageId } : {}),
    };
    const { data } = await apiClient.get<EmailReviewOptions>(
      API_ENDPOINTS.emailIntegrations.reviewOptions,
      { params: Object.keys(params).length > 0 ? params : undefined },
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

  intelligence: async (
    messageId: string,
  ): Promise<EmailIntelligenceDetail | null> => {
    try {
      const { data } = await apiClient.get<EmailIntelligenceDetail>(
        API_ENDPOINTS.emailIntegrations.messageIntelligence(messageId),
      );
      return data;
    } catch (error) {
      if (isNotFoundApiError(error)) return null;
      throw error;
    }
  },

  decideProposal: async ({
    proposalId,
    request,
  }: {
    proposalId: string;
    request: DecideEmailProposalRequest;
  }): Promise<EmailProposalDecisionResponse> => {
    const { data } = await apiClient.post<EmailProposalDecisionResponse>(
      API_ENDPOINTS.emailIntegrations.proposalDecision(proposalId),
      request,
    );
    return data;
  },

  decideDeadline: async ({
    deadlineId,
    request,
  }: {
    deadlineId: string;
    request: DecideEmailDeadlineRequest;
  }): Promise<EmailInboxDeadline> => {
    const { data } = await apiClient.post<EmailInboxDeadline>(
      API_ENDPOINTS.emailIntegrations.deadlineDecision(deadlineId),
      request,
    );
    return data;
  },

  decideDraft: async ({
    draftId,
    request,
  }: {
    draftId: string;
    request: DecideEmailDraftRequest;
  }): Promise<EmailInboxDraft> => {
    const { data } = await apiClient.post<EmailInboxDraft>(
      API_ENDPOINTS.emailIntegrations.draftDecision(draftId),
      request,
    );
    return data;
  },

  updateDraft: async ({
    draftId,
    request,
  }: {
    draftId: string;
    request: UpdateEmailReplyDraftRequest;
  }): Promise<EmailInboxDraft> => {
    const { data } = await apiClient.put<EmailInboxDraft>(
      API_ENDPOINTS.emailIntegrations.draft(draftId),
      request,
    );
    return data;
  },

  createIntelligenceFeedback: async ({
    analysisId,
    request,
  }: {
    analysisId: string;
    request: EmailAiFeedbackRequest;
  }): Promise<EmailAiFeedbackResponse> => {
    const { data } = await apiClient.post<EmailAiFeedbackResponse>(
      API_ENDPOINTS.emailIntegrations.analysisFeedback(analysisId),
      request,
    );
    return data;
  },

  retryIntelligence: async (
    analysisId: string,
  ): Promise<EmailAiRetryResponse> => {
    const { data } = await apiClient.post<EmailAiRetryResponse>(
      API_ENDPOINTS.emailIntegrations.analysisRetry(analysisId),
    );
    return data;
  },

  rolloutTargets: async ({
    scopeType,
    search,
  }: {
    scopeType: EmailAiRolloutScope;
    search?: string;
  }): Promise<EmailAiRolloutTargetsResponse> => {
    const { data } = await apiClient.get<EmailAiRolloutTargetsResponse>(
      API_ENDPOINTS.admin.emailAiRollout,
      {
        params: {
          scope_type: scopeType,
          search: search || undefined,
        },
      },
    );
    return data;
  },

  updateRolloutPolicy: async (
    request: UpdateEmailAiRolloutPolicyRequest,
  ): Promise<EmailAiRolloutTarget> => {
    const { data } = await apiClient.put<EmailAiRolloutTarget>(
      API_ENDPOINTS.admin.emailAiRollout,
      request,
    );
    return data;
  },
};

function isNotFoundApiError(error: unknown): error is ApiError {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === "HTTP_404"
  );
}

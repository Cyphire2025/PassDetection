"use client";

import { useLiveHistoryFeed } from "@/lib/hooks/use-live-history-feed";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";
import { emailIntegrationsApi } from "../api/email-integrations.api";
import { emailRepairIntervalMs } from "../services/email-refresh-policy";
import type {
  DecideEmailDeadlineRequest,
  DecideEmailDraftRequest,
  DecideEmailProposalRequest,
  EmailAiFeedbackRequest,
  EmailAiRolloutScope,
  EmailOperationalInboxResponse,
  EmailOperationalInboxView,
  ResolveEmailReviewRequest,
  UpdateEmailAiRolloutPolicyRequest,
  UpdateEmailReplyDraftRequest,
} from "../types";
import { isEmailProcessingActive } from "../utils/email-integrations";

export const EMAIL_INTEGRATION_QUERY_KEYS = {
  root: ["email-integrations"] as const,
  status: ["email-integrations", "status"] as const,
  connections: ["email-integrations", "connections"] as const,
  summary: ["email-integrations", "summary"] as const,
  inbox: (userId: string, view: EmailOperationalInboxView) =>
    ["email-integrations", "inbox", userId, { view }] as const,
  reviewsRoot: ["email-integrations", "reviews"] as const,
  reviews: (status: string) =>
    ["email-integrations", "reviews", { status }] as const,
  reviewOptions: (groupId?: string, messageId?: string) =>
    [
      "email-integrations",
      "review-options",
      {
        groupId: groupId ?? null,
        messageId: messageId ?? null,
      },
    ] as const,
  activity: ["email-integrations", "activity"] as const,
  message: (messageId: string) =>
    ["email-integrations", "messages", messageId] as const,
  intelligence: (messageId: string) =>
    ["email-integrations", "messages", messageId, "intelligence"] as const,
  rolloutRoot: (userId: string) =>
    ["email-integrations", "ai-rollout", userId] as const,
  rollout: (userId: string, scopeType: EmailAiRolloutScope, search: string) =>
    [
      "email-integrations",
      "ai-rollout",
      userId,
      { scopeType, search },
    ] as const,
};

const MISSING_INTELLIGENCE_POLL_WINDOW_MS = 2 * 60_000;
const ACTIVE_INTELLIGENCE_STATUSES = new Set(["pending", "processing"]);

export function useEmailIntegrationStatus() {
  return useQuery({
    queryKey: EMAIL_INTEGRATION_QUERY_KEYS.status,
    queryFn: emailIntegrationsApi.status,
  });
}

export function useEmailConnections() {
  return useQuery({
    queryKey: EMAIL_INTEGRATION_QUERY_KEYS.connections,
    queryFn: emailIntegrationsApi.connections,
    refetchInterval: () => emailRepairIntervalMs(),
    refetchIntervalInBackground: false,
  });
}

export function useEmailIntegrationSummary() {
  return useQuery({
    queryKey: EMAIL_INTEGRATION_QUERY_KEYS.summary,
    queryFn: emailIntegrationsApi.summary,
    refetchInterval: () => emailRepairIntervalMs(),
    refetchIntervalInBackground: false,
  });
}

export function useEmailReviews(status: string) {
  return useQuery({
    queryKey: EMAIL_INTEGRATION_QUERY_KEYS.reviews(status),
    queryFn: () => emailIntegrationsApi.reviews(status),
    refetchInterval: () => emailRepairIntervalMs(),
    refetchIntervalInBackground: false,
  });
}

export function useEmailReviewOptions(
  groupId?: string,
  enabled = true,
  messageId?: string,
) {
  return useQuery({
    queryKey: EMAIL_INTEGRATION_QUERY_KEYS.reviewOptions(groupId, messageId),
    queryFn: () => emailIntegrationsApi.reviewOptions(groupId, messageId),
    enabled,
  });
}

export function useEmailActivity() {
  return useQuery({
    queryKey: EMAIL_INTEGRATION_QUERY_KEYS.activity,
    queryFn: emailIntegrationsApi.activity,
    refetchInterval: () => emailRepairIntervalMs(),
    refetchIntervalInBackground: false,
  });
}

export function useEmailMessage(messageId: string) {
  return useQuery({
    queryKey: EMAIL_INTEGRATION_QUERY_KEYS.message(messageId),
    queryFn: () => emailIntegrationsApi.message(messageId),
    enabled: Boolean(messageId),
    refetchInterval: (query) =>
      query.state.data &&
      isEmailProcessingActive(query.state.data.processing_status)
        ? emailRepairIntervalMs({ active: true })
        : false,
  });
}

export function useEmailMessageIntelligence(
  messageId: string,
  {
    pollWhileMissing = false,
  }: {
    pollWhileMissing?: boolean;
  } = {},
) {
  const missingPollWindow = useRef<{
    messageId: string | null;
    pollWhileMissing: boolean;
    startedAt: number | null;
  }>({
    messageId: null,
    pollWhileMissing: false,
    startedAt: null,
  });

  return useQuery({
    queryKey: EMAIL_INTEGRATION_QUERY_KEYS.intelligence(messageId),
    queryFn: () => emailIntegrationsApi.intelligence(messageId),
    enabled: Boolean(messageId),
    retry: false,
    refetchInterval: (query) => {
      if (
        missingPollWindow.current.messageId !== messageId ||
        missingPollWindow.current.pollWhileMissing !== pollWhileMissing
      ) {
        missingPollWindow.current = {
          messageId,
          pollWhileMissing,
          startedAt: pollWhileMissing ? Date.now() : null,
        };
      }
      const intelligence = query.state.data;
      if (intelligence === null) {
        const pollStartedAt = missingPollWindow.current.startedAt;
        return pollWhileMissing &&
          pollStartedAt !== null &&
          Date.now() - pollStartedAt < MISSING_INTELLIGENCE_POLL_WINDOW_MS
          ? emailRepairIntervalMs({ active: true })
          : false;
      }
      return intelligence &&
        ACTIVE_INTELLIGENCE_STATUSES.has(intelligence.status.toLowerCase())
        ? emailRepairIntervalMs({ active: true })
        : false;
    },
    refetchIntervalInBackground: false,
  });
}

function useInvalidateEmailIntegrations() {
  const queryClient = useQueryClient();
  return () =>
    queryClient.invalidateQueries({
      queryKey: EMAIL_INTEGRATION_QUERY_KEYS.root,
      predicate: (query) => !query.meta?.historyOnly,
    });
}

export function useAuthorizeEmailProvider() {
  return useMutation({
    mutationFn: ({
      provider,
      connectionId,
    }: {
      provider: "gmail" | "outlook";
      connectionId?: string;
    }) => emailIntegrationsApi.authorize(provider, connectionId),
  });
}

export function useEmailOperationalInbox(
  userId: string | null | undefined,
  view: EmailOperationalInboxView,
) {
  return useLiveHistoryFeed<EmailOperationalInboxResponse>({
    queryKey: EMAIL_INTEGRATION_QUERY_KEYS.inbox(userId ?? "anonymous", view),
    itemKey: (item) => item.message_id,
    loadPage: (cursor, signal) =>
      emailIntegrationsApi.inbox({ view, limit: 20, cursor, signal }),
    enabled: Boolean(userId),
    interval: () => emailRepairIntervalMs(),
  });
}

export function useSyncEmailConnection() {
  const invalidate = useInvalidateEmailIntegrations();
  return useMutation({
    mutationFn: emailIntegrationsApi.syncConnection,
    onSuccess: invalidate,
  });
}

export function useUpdateEmailAiSettings() {
  const invalidate = useInvalidateEmailIntegrations();
  return useMutation({
    mutationFn: ({
      connectionId,
      enabled,
    }: {
      connectionId: string;
      enabled: boolean;
    }) => emailIntegrationsApi.updateAiSettings({ connectionId, enabled }),
    // The server may have committed the preference even when the response was
    // interrupted, so reconcile the card after both success and failure.
    onSettled: invalidate,
  });
}

export function usePauseEmailConnection() {
  const invalidate = useInvalidateEmailIntegrations();
  return useMutation({
    mutationFn: emailIntegrationsApi.pauseConnection,
    onSuccess: invalidate,
  });
}

export function useResumeEmailConnection() {
  const invalidate = useInvalidateEmailIntegrations();
  return useMutation({
    mutationFn: emailIntegrationsApi.resumeConnection,
    onSuccess: invalidate,
  });
}

export function useDisconnectEmailConnection() {
  const invalidate = useInvalidateEmailIntegrations();
  return useMutation({
    mutationFn: emailIntegrationsApi.disconnectConnection,
    // A failed provider revocation deliberately leaves the connection in a
    // retryable blocked state, so refresh the card on both outcomes.
    onSettled: invalidate,
  });
}

export function useResolveEmailReview() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      reviewId,
      request,
    }: {
      reviewId: string;
      request: ResolveEmailReviewRequest;
    }) => emailIntegrationsApi.resolveReview({ reviewId, request }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: EMAIL_INTEGRATION_QUERY_KEYS.reviewsRoot,
        }),
        queryClient.invalidateQueries({
          queryKey: EMAIL_INTEGRATION_QUERY_KEYS.summary,
        }),
        queryClient.invalidateQueries({
          queryKey: EMAIL_INTEGRATION_QUERY_KEYS.activity,
        }),
      ]);
    },
  });
}

export function useRemoveEmailConnection() {
  const invalidate = useInvalidateEmailIntegrations();
  return useMutation({
    mutationFn: emailIntegrationsApi.removeConnection,
    // Provider revocation failures keep the card in a retryable blocked state;
    // successful removal clears every owner-scoped email integration view.
    onSettled: invalidate,
  });
}

export function useDecideEmailProposal() {
  const invalidate = useInvalidateEmailIntegrations();
  return useMutation({
    mutationFn: ({
      proposalId,
      request,
    }: {
      proposalId: string;
      request: DecideEmailProposalRequest;
    }) => emailIntegrationsApi.decideProposal({ proposalId, request }),
    onSuccess: invalidate,
    onError: invalidate,
  });
}

export function useDecideEmailDeadline() {
  const invalidate = useInvalidateEmailIntegrations();
  return useMutation({
    mutationFn: ({
      deadlineId,
      request,
    }: {
      deadlineId: string;
      request: DecideEmailDeadlineRequest;
    }) => emailIntegrationsApi.decideDeadline({ deadlineId, request }),
    onSuccess: invalidate,
    onError: invalidate,
  });
}

export function useDecideEmailReplyDraft() {
  const invalidate = useInvalidateEmailIntegrations();
  return useMutation({
    mutationFn: ({
      draftId,
      request,
    }: {
      draftId: string;
      request: DecideEmailDraftRequest;
    }) => emailIntegrationsApi.decideDraft({ draftId, request }),
    onSuccess: invalidate,
    onError: invalidate,
  });
}

export function useUpdateEmailReplyDraft() {
  const invalidate = useInvalidateEmailIntegrations();
  return useMutation({
    mutationFn: ({
      draftId,
      request,
    }: {
      draftId: string;
      request: UpdateEmailReplyDraftRequest;
    }) => emailIntegrationsApi.updateDraft({ draftId, request }),
    onSuccess: invalidate,
    onError: invalidate,
  });
}

export function useCreateEmailIntelligenceFeedback() {
  const invalidate = useInvalidateEmailIntegrations();
  return useMutation({
    mutationFn: ({
      analysisId,
      request,
    }: {
      analysisId: string;
      request: EmailAiFeedbackRequest;
    }) =>
      emailIntegrationsApi.createIntelligenceFeedback({
        analysisId,
        request,
      }),
    onSuccess: invalidate,
    onError: invalidate,
  });
}

export function useRetryEmailIntelligence() {
  const invalidate = useInvalidateEmailIntegrations();
  return useMutation({
    mutationFn: (analysisId: string) =>
      emailIntegrationsApi.retryIntelligence(analysisId),
    onSuccess: invalidate,
    onError: invalidate,
  });
}

export function useEmailAiRolloutTargets(
  userId: string | null | undefined,
  scopeType: EmailAiRolloutScope,
  search: string,
  enabled: boolean,
) {
  return useQuery({
    queryKey: EMAIL_INTEGRATION_QUERY_KEYS.rollout(
      userId ?? "anonymous",
      scopeType,
      search,
    ),
    queryFn: () =>
      emailIntegrationsApi.rolloutTargets({
        scopeType,
        search: search || undefined,
      }),
    enabled: Boolean(userId) && enabled,
    refetchOnWindowFocus: true,
  });
}

export function useUpdateEmailAiRolloutPolicy(
  userId: string | null | undefined,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: UpdateEmailAiRolloutPolicyRequest) =>
      emailIntegrationsApi.updateRolloutPolicy(request),
    onSettled: () => {
      if (!userId) return Promise.resolve();
      return queryClient.invalidateQueries({
        queryKey: EMAIL_INTEGRATION_QUERY_KEYS.rolloutRoot(userId),
      });
    },
  });
}

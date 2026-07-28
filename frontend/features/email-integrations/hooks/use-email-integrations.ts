"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { emailIntegrationsApi } from "../api/email-integrations.api";
import type { ResolveEmailReviewRequest } from "../types";
import { isEmailProcessingActive } from "../utils/email-integrations";

export const EMAIL_INTEGRATION_QUERY_KEYS = {
  root: ["email-integrations"] as const,
  status: ["email-integrations", "status"] as const,
  connections: ["email-integrations", "connections"] as const,
  summary: ["email-integrations", "summary"] as const,
  reviewsRoot: ["email-integrations", "reviews"] as const,
  reviews: (status: string) =>
    ["email-integrations", "reviews", { status }] as const,
  reviewOptions: (groupId?: string) =>
    ["email-integrations", "review-options", { groupId: groupId ?? null }] as const,
  activity: ["email-integrations", "activity"] as const,
  message: (messageId: string) =>
    ["email-integrations", "messages", messageId] as const,
};

const REFRESH_INTERVAL_MS = 30_000;

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
    refetchInterval: REFRESH_INTERVAL_MS,
  });
}

export function useEmailIntegrationSummary() {
  return useQuery({
    queryKey: EMAIL_INTEGRATION_QUERY_KEYS.summary,
    queryFn: emailIntegrationsApi.summary,
    refetchInterval: REFRESH_INTERVAL_MS,
  });
}

export function useEmailReviews(status: string) {
  return useQuery({
    queryKey: EMAIL_INTEGRATION_QUERY_KEYS.reviews(status),
    queryFn: () => emailIntegrationsApi.reviews(status),
    refetchInterval: REFRESH_INTERVAL_MS,
  });
}

export function useEmailReviewOptions(groupId?: string) {
  return useQuery({
    queryKey: EMAIL_INTEGRATION_QUERY_KEYS.reviewOptions(groupId),
    queryFn: () => emailIntegrationsApi.reviewOptions(groupId),
  });
}

export function useEmailActivity() {
  return useQuery({
    queryKey: EMAIL_INTEGRATION_QUERY_KEYS.activity,
    queryFn: emailIntegrationsApi.activity,
    refetchInterval: REFRESH_INTERVAL_MS,
  });
}

export function useEmailMessage(messageId: string) {
  return useQuery({
    queryKey: EMAIL_INTEGRATION_QUERY_KEYS.message(messageId),
    queryFn: () => emailIntegrationsApi.message(messageId),
    enabled: Boolean(messageId),
    refetchInterval: (query) =>
      query.state.data
      && isEmailProcessingActive(query.state.data.processing_status)
        ? 5_000
        : false,
  });
}

function useInvalidateEmailIntegrations() {
  const queryClient = useQueryClient();
  return () =>
    queryClient.invalidateQueries({
      queryKey: EMAIL_INTEGRATION_QUERY_KEYS.root,
    });
}

export function useAuthorizeGmail() {
  return useMutation({
    mutationFn: (connectionId?: string) =>
      emailIntegrationsApi.authorizeGmail(connectionId),
  });
}

export function useSyncEmailConnection() {
  const invalidate = useInvalidateEmailIntegrations();
  return useMutation({
    mutationFn: emailIntegrationsApi.syncConnection,
    onSuccess: invalidate,
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

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { QUERY_KEYS } from "@/constants";
import { operationsApi } from "../api/operations.api";

export function useAdminOverview() {
  return useQuery({
    queryKey: QUERY_KEYS.operations.adminOverview,
    queryFn: operationsApi.adminOverview,
  });
}

export function useManagers() {
  return useQuery({
    queryKey: QUERY_KEYS.operations.managers,
    queryFn: operationsApi.managers,
  });
}

export function useCreateManager() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: operationsApi.createManager,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.managers });
    },
  });
}

export function useAnalyticsSummary(days = 30) {
  return useQuery({
    queryKey: QUERY_KEYS.operations.analytics({ days }),
    queryFn: () => operationsApi.analyticsSummary(days),
  });
}

export function useAuditLogs() {
  return useQuery({
    queryKey: QUERY_KEYS.operations.auditLogs(),
    queryFn: operationsApi.auditLogs,
    refetchInterval: 30_000,
  });
}

export function useNotifications(unreadOnly = false) {
  return useQuery({
    queryKey: QUERY_KEYS.operations.notifications({ unreadOnly }),
    queryFn: () => operationsApi.notifications(unreadOnly),
    refetchInterval: 30_000,
  });
}

export function useMarkNotificationRead() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: operationsApi.markNotificationRead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.notifications() });
    },
  });
}

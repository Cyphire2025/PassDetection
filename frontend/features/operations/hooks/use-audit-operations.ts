import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { usePrivateMutation } from "@/hooks/use-private-mutation";
import { QUERY_KEYS } from "@/constants";
import { operationsApi, type AuditLogFilters } from "../api/operations.api";
import { useAuthenticatedQueryScope } from "./operations-query-scope";

export function useAnalyticsSummary(days = 30) {
  return useQuery({
    queryKey: QUERY_KEYS.operations.analytics({ days }),
    queryFn: () => operationsApi.analyticsSummary(days),
  });
}

export function useAuditLogPages(filters: AuditLogFilters) {
  const accessScope = useAuthenticatedQueryScope();
  return useInfiniteQuery({
    queryKey: [...QUERY_KEYS.operations.auditLogs(filters), accessScope],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => operationsApi.auditLogPage({
      filters,
      cursor: pageParam,
      signal,
    }),
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    refetchOnWindowFocus: true,
    retry: false,
  });
}

export function useAuditLogExport() {
  return usePrivateMutation({
    mutationFn: ({
      filters,
      signal,
    }: {
      filters: AuditLogFilters & { start_at: string; end_at: string };
      signal: AbortSignal;
    }) => operationsApi.exportAuditLogs({ filters, signal }),
  });
}

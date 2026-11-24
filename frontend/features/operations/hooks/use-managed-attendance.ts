import { useEffect } from "react";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { usePrivateMutation } from "@/hooks/use-private-mutation";
import { QUERY_KEYS } from "@/constants";
import { operationsApi, type GroupAttendanceSummary } from "../api/operations.api";
import {
  attendanceRepairIntervalMs,
  publishAttendanceInvalidationHint,
  subscribeAttendanceInvalidationHints,
} from "../services/attendance-invalidation";
import { useAuthenticatedQueryScope } from "./operations-query-scope";

export function useCompleteManagedAttendanceSession() {
  const queryClient = useQueryClient();
  return usePrivateMutation({
    mutationFn: operationsApi.completeManagedAttendanceSession,
    onSuccess: (_data, variables) => {
      publishAttendanceInvalidationHint({
        groupId: variables.groupId,
        sessionId: variables.sessionId,
        source: "local-mutation",
      });
      void queryClient.invalidateQueries({
        queryKey: ["operations", "tour-operations", "groups", variables.groupId, "attendance"],
      });
      void queryClient.invalidateQueries({
        queryKey: [...QUERY_KEYS.operations.tourGroupPassengers(variables.groupId), "sessions"],
      });
    },
  });
}

export function useCreateManagedAttendanceSession() {
  const queryClient = useQueryClient();

  return usePrivateMutation({
    mutationFn: operationsApi.createManagedAttendanceSession,
    onSuccess: (data, variables) => {
      publishAttendanceInvalidationHint({
        groupId: variables.groupId,
        sessionId: data.id,
        source: "local-mutation",
      });
      queryClient.invalidateQueries({
        queryKey: ["operations", "tour-operations", "groups", variables.groupId, "attendance"],
      });
      queryClient.invalidateQueries({
        queryKey: [...QUERY_KEYS.operations.tourGroupPassengers(variables.groupId), "sessions"],
      });
    },
  });
}

export function useGroupAttendanceSummary(groupId: string) {
  const queryClient = useQueryClient();
  const accessScope = useAuthenticatedQueryScope();
  const queryKey = [
    "operations",
    "tour-operations",
    "groups",
    groupId,
    "attendance",
    "summary",
    accessScope,
  ] as const;
  useEffect(() => subscribeAttendanceInvalidationHints((hint) => {
    if (hint.groupId !== groupId) return;
    void queryClient.invalidateQueries({
      queryKey: [
        "operations",
        "tour-operations",
        "groups",
        groupId,
        "attendance",
        "summary",
        accessScope,
      ],
    });
  }), [accessScope, groupId, queryClient]);
  return useQuery({
    queryKey,
    queryFn: ({ signal }) => operationsApi.groupAttendanceSummary({
      groupId,
      previous: queryClient.getQueryData<GroupAttendanceSummary>(queryKey),
      signal,
    }),
    refetchInterval: (query) => attendanceRepairIntervalMs({
      groupId,
      accessScope,
      hasActiveSession: query.state.data?.sessions.some(
        (session) => session.status === "draft" || session.status === "active",
      ) ?? false,
    }),
    refetchIntervalInBackground: false,
    refetchOnReconnect: "always",
    refetchOnWindowFocus: "always",
    retry: false,
  });
}

export function useGroupAttendanceMissingPassengers({
  groupId,
  sessionId,
  revision,
  search,
  enabled,
}: {
  groupId: string;
  sessionId: string | null;
  revision: string | null;
  search: string;
  enabled: boolean;
}) {
  const accessScope = useAuthenticatedQueryScope();
  return useInfiniteQuery({
    queryKey: [
      "operations",
      "tour-operations",
      "groups",
      groupId,
      "attendance",
      "missing",
      sessionId ?? "none",
      revision ?? "none",
      search,
      accessScope,
    ],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => {
      if (!sessionId || !revision) {
        throw new Error("Missing-passenger queries require an activity revision");
      }
      return operationsApi.groupAttendanceMissingPassengers({
        groupId,
        sessionId,
        revision,
        cursor: pageParam,
        search,
        signal,
      });
    },
    enabled: enabled && Boolean(sessionId) && Boolean(revision),
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    retry: false,
  });
}

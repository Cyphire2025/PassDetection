import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { QUERY_KEYS } from "@/constants";
import { operationsApi } from "../api/operations.api";
import { attendanceRepairIntervalMs, subscribeAttendanceInvalidationHints } from "../services/attendance-invalidation";
import { useAuthenticatedQueryScope } from "./operations-query-scope";

export function useMyTourGroups(enabled = true) {
  return useQuery({
    queryKey: [...QUERY_KEYS.operations.tourGroups, "mine"],
    queryFn: operationsApi.myTourGroups,
    enabled,
    retry: false,
  });
}

export function useMyTourGroupPassengers(groupId: string | null, enabled = true) {
  return useQuery({
    queryKey: [...QUERY_KEYS.operations.tourGroupPassengers(groupId ?? "none"), "mine"],
    queryFn: () => operationsApi.myTourGroupPassengers(groupId as string),
    enabled: enabled && Boolean(groupId),
    retry: false,
  });
}

export function useMyTourGroupPassenger(groupId: string | null, passengerId: string | null, enabled = true) {
  return useQuery({
    queryKey: [...QUERY_KEYS.operations.tourGroupPassengers(groupId ?? "none"), "mine", passengerId ?? "none"],
    queryFn: () => operationsApi.myTourGroupPassenger(groupId as string, passengerId as string),
    enabled: enabled && Boolean(groupId) && Boolean(passengerId),
    retry: false,
  });
}

export function useMyAttendanceSessions(groupId: string | null, enabled = true) {
  const queryClient = useQueryClient();
  const accessScope = useAuthenticatedQueryScope();
  const resolvedGroupId = groupId ?? "none";
  const queryKey = [...QUERY_KEYS.operations.tourGroupPassengers(resolvedGroupId), "sessions"] as const;
  useEffect(() => subscribeAttendanceInvalidationHints((hint) => {
    if (hint.groupId !== groupId) return;
    void queryClient.invalidateQueries({
      queryKey: [...QUERY_KEYS.operations.tourGroupPassengers(resolvedGroupId), "sessions"],
    });
  }), [groupId, queryClient, resolvedGroupId]);

  return useQuery({
    queryKey,
    queryFn: () => operationsApi.myAttendanceSessions(groupId as string),
    enabled: enabled && Boolean(groupId),
    retry: false,
    refetchInterval: (query) => attendanceRepairIntervalMs({
      groupId: resolvedGroupId,
      accessScope,
      hasActiveSession: query.state.data?.some(
        (session) => session.status === "draft" || session.status === "active",
      ) ?? false,
    }),
    refetchIntervalInBackground: false,
    refetchOnReconnect: "always",
    refetchOnWindowFocus: "always",
    staleTime: 2_000,
  });
}

export function useMyAttendanceSessionDetails(sessionId: string | null, enabled = true) {
  return useQuery({
    queryKey: ["operations", "tour-operations", "coordinator", "sessions", sessionId ?? "none", "details"],
    queryFn: () => operationsApi.myAttendanceSessionDetails(sessionId as string),
    enabled: enabled && Boolean(sessionId),
    retry: false,
  });
}

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

export function useAdminGroups() {
  return useQuery({
    queryKey: QUERY_KEYS.operations.adminGroups,
    queryFn: operationsApi.adminGroups,
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

export function useDeleteManager() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ managerId, deleteOwnedData }: { managerId: string; deleteOwnedData: boolean }) =>
      operationsApi.deleteManager(managerId, deleteOwnedData),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.managers });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.adminGroups });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.dashboard.stats });
    },
  });
}

export function useAssignManagerGroups() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ managerId, groupIds }: { managerId: string; groupIds: string[] }) =>
      operationsApi.assignManagerGroups(managerId, groupIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.managers });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.adminGroups });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.dashboard.stats });
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

export function useTourOperationsArchitecture() {
  return useQuery({
    queryKey: QUERY_KEYS.operations.tourOperationsArchitecture,
    queryFn: operationsApi.tourOperationsArchitecture,
  });
}

export function useTourCoordinators() {
  return useQuery({
    queryKey: QUERY_KEYS.operations.tourCoordinators,
    queryFn: operationsApi.tourCoordinators,
    retry: false,
  });
}

export function useCreateTourCoordinator() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: operationsApi.createTourCoordinator,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.tourCoordinators });
    },
  });
}

export function useTourGroups() {
  return useQuery({
    queryKey: QUERY_KEYS.operations.tourGroups,
    queryFn: operationsApi.tourGroups,
    retry: false,
  });
}

export function useAssignTourGroupCoordinators() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ groupId, coordinatorIds }: { groupId: string; coordinatorIds: string[] }) =>
      operationsApi.assignTourGroupCoordinators(groupId, coordinatorIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.tourGroups });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.tourCoordinators });
    },
  });
}

export function useTourGroupPassengers(groupId: string | null) {
  return useQuery({
    queryKey: QUERY_KEYS.operations.tourGroupPassengers(groupId ?? "none"),
    queryFn: () => operationsApi.tourGroupPassengers(groupId as string),
    enabled: Boolean(groupId),
    retry: false,
  });
}

export function useAssignTourGroupPassengers() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      groupId,
      passengerIds,
      coordinatorId,
    }: {
      groupId: string;
      passengerIds: string[];
      coordinatorId: string | null;
    }) => operationsApi.assignTourGroupPassengers(groupId, passengerIds, coordinatorId),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.tourGroupPassengers(variables.groupId) });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.tourGroups });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.tourCoordinators });
    },
  });
}

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

export function useCreateMyAttendanceSession() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ groupId, name }: { groupId: string; name: string }) =>
      operationsApi.createMyAttendanceSession(groupId, name),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: [...QUERY_KEYS.operations.tourGroupPassengers(variables.groupId), "sessions"] });
    },
  });
}

export function useMyAttendanceSessions(groupId: string | null, enabled = true) {
  return useQuery({
    queryKey: [...QUERY_KEYS.operations.tourGroupPassengers(groupId ?? "none"), "sessions"],
    queryFn: () => operationsApi.myAttendanceSessions(groupId as string),
    enabled: enabled && Boolean(groupId),
    retry: false,
  });
}

export function useScanMyAttendanceSession() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: operationsApi.scanMyAttendanceSession,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.tourGroups });
    },
  });
}

export function useCompleteMyAttendanceSession() {
  return useMutation({
    mutationFn: operationsApi.completeMyAttendanceSession,
  });
}

export function useGroupAttendanceOverview(groupId: string) {
  return useQuery({
    queryKey: ["operations", "tour-operations", "groups", groupId, "attendance"],
    queryFn: () => operationsApi.groupAttendanceOverview(groupId),
    refetchInterval: 10_000,
    retry: false,
  });
}

export function useGroupQrCodes(groupId: string) {
  return useQuery({
    queryKey: QUERY_KEYS.operations.tourGroupQrCodes(groupId),
    queryFn: () => operationsApi.groupQrCodes(groupId),
    retry: false,
  });
}

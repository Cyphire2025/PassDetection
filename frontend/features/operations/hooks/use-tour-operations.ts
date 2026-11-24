import { useQuery, useQueryClient } from "@tanstack/react-query";
import { usePrivateMutation } from "@/hooks/use-private-mutation";
import { QUERY_KEYS } from "@/constants";
import { operationsApi } from "../api/operations.api";

export function useTourCoordinators() {
  return useQuery({
    queryKey: QUERY_KEYS.operations.tourCoordinators,
    queryFn: operationsApi.tourCoordinators,
    retry: false,
  });
}

export function useCreateTourCoordinator() {
  const queryClient = useQueryClient();

  return usePrivateMutation({
    mutationFn: operationsApi.createTourCoordinator,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.tourCoordinators });
    },
  });
}

export function useTourGroups(assignmentEligibleOnly = false) {
  return useQuery({
    queryKey: assignmentEligibleOnly
      ? [...QUERY_KEYS.operations.tourGroups, "assignment-eligible"]
      : QUERY_KEYS.operations.tourGroups,
    queryFn: () => operationsApi.tourGroups(assignmentEligibleOnly),
    refetchInterval: assignmentEligibleOnly ? 60_000 : false,
    refetchIntervalInBackground: false,
    retry: false,
  });
}

export function useAssignTourGroupCoordinators() {
  const queryClient = useQueryClient();

  return usePrivateMutation({
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

  return usePrivateMutation({
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

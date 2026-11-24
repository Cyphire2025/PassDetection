import { useQuery, useQueryClient } from "@tanstack/react-query";
import { usePrivateMutation } from "@/hooks/use-private-mutation";
import { QUERY_KEYS } from "@/constants";
import { operationsApi } from "../api/operations.api";

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

  return usePrivateMutation({
    mutationFn: operationsApi.createManager,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.managers });
    },
  });
}

export function useDeleteManager() {
  const queryClient = useQueryClient();

  return usePrivateMutation({
    mutationFn: ({ managerId, deleteOwnedData }: { managerId: string; deleteOwnedData: boolean }) =>
      operationsApi.deleteManager(managerId, deleteOwnedData),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.managers });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.adminGroups });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.dashboard.stats });
    },
  });
}

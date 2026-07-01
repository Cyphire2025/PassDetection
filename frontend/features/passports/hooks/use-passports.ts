import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { QUERY_KEYS } from "@/constants";
import { passportsApi } from "../api/passports.api";

export function usePassports() {
  return useQuery({
    queryKey: QUERY_KEYS.passports.list(),
    queryFn: () => passportsApi.list(),
    refetchInterval: 30_000,
  });
}

export function usePassportGroups() {
  return useQuery({
    queryKey: QUERY_KEYS.passports.groups(),
    queryFn: () => passportsApi.listGroups(),
    refetchInterval: 30_000,
  });
}

export function usePassportsByGroup(groupId: string, search?: string) {
  return useQuery({
    queryKey: QUERY_KEYS.passports.groupDetail(groupId, { search }),
    queryFn: () => passportsApi.listByGroup(groupId, search),
    enabled: Boolean(groupId),
    refetchInterval: 30_000,
  });
}

export function useExportPassportGroup() {
  return useMutation({
    mutationFn: (groupId: string) => passportsApi.exportGroup(groupId),
  });
}

export function usePassportSubmission(id: string) {
  return useQuery({
    queryKey: QUERY_KEYS.passports.detail(id),
    queryFn: () => passportsApi.getById(id),
    enabled: Boolean(id),
  });
}

export function useConfirmPassportSubmission(id: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (confirmedFields: Record<string, string>) => passportsApi.confirm(id, confirmedFields),
    onSuccess: (updated) => {
      queryClient.setQueryData(QUERY_KEYS.passports.detail(id), updated);
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.passports.all });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.dashboard.stats });
    },
  });
}

export function useReextractPassportSubmission() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => passportsApi.reextract(id),
    onSuccess: (updated) => {
      queryClient.setQueryData(QUERY_KEYS.passports.detail(updated.id), updated);
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.passports.all });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.dashboard.stats });
    },
  });
}

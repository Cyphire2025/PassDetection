import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  passportRetentionApi,
  type UpdatePassportRetentionControl,
} from "../api/passport-retention.api";

export const passportRetentionQueryKey = (groupId: string) => [
  "passport-retention",
  groupId,
] as const;

export function usePassportRetention(groupId: string, enabled = true) {
  return useQuery({
    queryKey: passportRetentionQueryKey(groupId),
    queryFn: () => passportRetentionApi.get(groupId),
    enabled: enabled && Boolean(groupId),
    staleTime: 30_000,
  });
}

export function useUpdatePassportRetention(groupId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: UpdatePassportRetentionControl) =>
      passportRetentionApi.update(groupId, request),
    onSuccess: (retention) => {
      queryClient.setQueryData(passportRetentionQueryKey(groupId), retention);
    },
  });
}

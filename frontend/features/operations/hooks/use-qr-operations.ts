import { useQuery, useQueryClient } from "@tanstack/react-query";
import { usePrivateMutation } from "@/hooks/use-private-mutation";
import { QUERY_KEYS } from "@/constants";
import { operationsApi } from "../api/operations.api";

export function useGroupQrCodes(groupId: string) {
  return useQuery({
    queryKey: QUERY_KEYS.operations.tourGroupQrCodes(groupId),
    queryFn: () => operationsApi.groupQrCodes(groupId),
    retry: false,
  });
}

export function useQrDeliveryPreview(groupId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["operations", "tour-operations", "groups", groupId, "qr-whatsapp-preview"],
    queryFn: () => operationsApi.qrDeliveryPreview(groupId),
    enabled,
    refetchInterval: (query) =>
      enabled && (query.state.data?.summary.in_progress ?? 0) > 0
        ? 1_500
        : false,
    refetchIntervalInBackground: false,
    retry: false,
  });
}

export function useSendQrBroadcast(groupId: string) {
  const queryClient = useQueryClient();
  return usePrivateMutation({
    mutationFn: (body: { qr_token_ids: string[]; message_content: string }) =>
      operationsApi.sendQrBroadcast(groupId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["operations", "tour-operations", "groups", groupId, "qr-whatsapp-preview"],
      });
    },
  });
}

export function usePassengerQrLifecycle(groupId: string) {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.tourGroupQrCodes(groupId) });
  const refreshPassenger = (passengerId: string) => {
    void refresh();
    void queryClient.invalidateQueries({ queryKey: QUERY_KEYS.passports.detail(passengerId) });
  };

  return {
    generate: usePrivateMutation({
      mutationFn: (passengerId: string) => operationsApi.generatePassengerQr(groupId, passengerId),
      onSuccess: (_data, passengerId) => refreshPassenger(passengerId),
    }),
    regenerate: usePrivateMutation({
      mutationFn: (passengerId: string) => operationsApi.regeneratePassengerQr(groupId, passengerId),
      onSuccess: (_data, passengerId) => refreshPassenger(passengerId),
    }),
    revoke: usePrivateMutation({
      mutationFn: (passengerId: string) => operationsApi.revokePassengerQr(groupId, passengerId),
      onSuccess: (_data, passengerId) => refreshPassenger(passengerId),
    }),
    setActive: usePrivateMutation({
      mutationFn: ({ passengerId, isActive }: { passengerId: string; isActive: boolean }) =>
        operationsApi.setPassengerQrActive(groupId, passengerId, isActive),
      onSuccess: (_data, variables) => refreshPassenger(variables.passengerId),
    }),
    expire: usePrivateMutation({
      mutationFn: (passengerId: string) =>
        operationsApi.setPassengerQrExpiration(groupId, passengerId, new Date().toISOString()),
      onSuccess: (_data, passengerId) => refreshPassenger(passengerId),
    }),
  };
}

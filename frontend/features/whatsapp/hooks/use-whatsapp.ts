import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { whatsappApi } from "../api/whatsapp.api";

export const WHATSAPP_QUERY_KEYS = {
  groups: ["whatsapp", "groups"] as const,
  group: (groupId: string) => ["whatsapp", "groups", groupId] as const,
};

export function useWhatsAppGroups() {
  return useQuery({
    queryKey: WHATSAPP_QUERY_KEYS.groups,
    queryFn: whatsappApi.groups,
  });
}

export function useWhatsAppGroup(groupId: string | null) {
  return useQuery({
    queryKey: groupId ? WHATSAPP_QUERY_KEYS.group(groupId) : ["whatsapp", "groups", "none"],
    queryFn: () => whatsappApi.group(groupId as string),
    enabled: Boolean(groupId),
  });
}

export function useCreateWhatsAppGroup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: whatsappApi.createGroup,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: WHATSAPP_QUERY_KEYS.groups });
    },
  });
}

export function useDeleteWhatsAppGroup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: whatsappApi.deleteGroup,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: WHATSAPP_QUERY_KEYS.groups });
    },
  });
}

export function useSendWhatsAppWelcome() {
  return useMutation({
    mutationFn: whatsappApi.sendWelcome,
  });
}

export function useSendWhatsAppPassportLink() {
  return useMutation({
    mutationFn: ({ groupId, passportLink }: { groupId: string; passportLink: string }) =>
      whatsappApi.sendPassportLink(groupId, passportLink),
  });
}

"use client";

import { useQueryClient } from "@tanstack/react-query";
import { usePrivateMutation } from "@/hooks/use-private-mutation";
import { whatsappApi } from "../api/whatsapp.api";
import { type CreateWhatsAppGroupInput, whatsappSourceGroupsApi } from "../api/whatsapp-source-groups.api";
import { WHATSAPP_QUERY_KEYS } from "./whatsapp-query-keys";

function useWhatsAppArchiveMutation(restore: boolean) {
  const queryClient = useQueryClient();
  return usePrivateMutation({
    mutationFn: restore ? whatsappApi.restoreGroup : whatsappApi.archiveGroup,
    onSuccess: async (group) => {
      queryClient.setQueryData(WHATSAPP_QUERY_KEYS.group(group.id), group);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: WHATSAPP_QUERY_KEYS.groups }),
        queryClient.invalidateQueries({
          queryKey: ["upload-links"],
          predicate: (query) => query.queryKey[2] === "whatsapp-broadcast-options"
            || query.queryKey[2] === "whatsapp-links",
        }),
      ]);
    },
  });
}

export function useArchiveWhatsAppGroup() {
  return useWhatsAppArchiveMutation(false);
}

export function useRestoreWhatsAppGroup() {
  return useWhatsAppArchiveMutation(true);
}

export function useCreateWhatsAppGroup() {
  const queryClient = useQueryClient();
  return usePrivateMutation({
    mutationFn: (input: CreateWhatsAppGroupInput) => "sourceGroupId" in input
      ? whatsappSourceGroupsApi.create(input)
      : whatsappApi.createGroup(input),
    onSuccess: async (group) => {
      queryClient.setQueryData(WHATSAPP_QUERY_KEYS.group(group.id), group);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: WHATSAPP_QUERY_KEYS.groups }),
        queryClient.invalidateQueries({
          queryKey: ["upload-links"],
          predicate: (query) => query.queryKey[2] === "whatsapp-broadcast-options"
            || query.queryKey[2] === "whatsapp-links",
        }),
      ]);
    },
  });
}

export function useUpdateWhatsAppGroup() {
  const queryClient = useQueryClient();
  return usePrivateMutation({
    mutationFn: whatsappApi.updateGroup,
    onSuccess: (group) => {
      queryClient.setQueryData(WHATSAPP_QUERY_KEYS.group(group.id), group);
      queryClient.invalidateQueries({ queryKey: WHATSAPP_QUERY_KEYS.groups });
    },
  });
}

export function useDeleteWhatsAppGroup() {
  const queryClient = useQueryClient();
  return usePrivateMutation({
    mutationFn: whatsappApi.deleteGroup,
    onSuccess: (_, groupId) => {
      queryClient.removeQueries({ queryKey: WHATSAPP_QUERY_KEYS.group(groupId) });
      queryClient.invalidateQueries({ queryKey: WHATSAPP_QUERY_KEYS.groups });
    },
  });
}

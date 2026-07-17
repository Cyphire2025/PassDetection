import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { WhatsAppBroadcastGroupDetail } from "../api/whatsapp.api";
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

export function useUpdateWhatsAppGroup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: whatsappApi.updateGroup,
    onSuccess: (group) => {
      queryClient.setQueryData(WHATSAPP_QUERY_KEYS.group(group.id), group);
      queryClient.invalidateQueries({ queryKey: WHATSAPP_QUERY_KEYS.groups });
    },
  });
}

export function useAddWhatsAppRecipients() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: whatsappApi.addRecipients,
    onSuccess: (group) => {
      queryClient.setQueryData(WHATSAPP_QUERY_KEYS.group(group.id), group);
      queryClient.invalidateQueries({ queryKey: WHATSAPP_QUERY_KEYS.groups });
    },
  });
}

export function useDeleteWhatsAppGroup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: whatsappApi.deleteGroup,
    onSuccess: (_, groupId) => {
      queryClient.removeQueries({ queryKey: WHATSAPP_QUERY_KEYS.group(groupId) });
      queryClient.invalidateQueries({ queryKey: WHATSAPP_QUERY_KEYS.groups });
    },
  });
}

export function useDeleteWhatsAppRecipient() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: whatsappApi.deleteRecipient,
    onSuccess: (_, { groupId, recipientId }) => {
      queryClient.setQueryData<WhatsAppBroadcastGroupDetail>(
        WHATSAPP_QUERY_KEYS.group(groupId),
        (current) => current
          ? {
              ...current,
              recipient_count: Math.max(0, current.recipient_count - 1),
              recipients: current.recipients.filter(
                (recipient) => recipient.id !== recipientId,
              ),
            }
          : current,
      );
      queryClient.invalidateQueries({ queryKey: WHATSAPP_QUERY_KEYS.group(groupId) });
      queryClient.invalidateQueries({ queryKey: WHATSAPP_QUERY_KEYS.groups });
    },
  });
}

export const WHATSAPP_BATCH_POLL_LIMIT_MS = 10 * 60 * 1000;

export function useWhatsAppBatchStatus(batchId: string | null, batchStartedAt: number | null) {
  return useQuery({
    queryKey: ["whatsapp", "batches", batchId],
    queryFn: () => whatsappApi.batchStatus(batchId as string),
    enabled: Boolean(batchId),
    refetchInterval: (query) => {
      const pollingStartedAt = batchStartedAt ?? query.state.dataUpdatedAt;
      const stillWithinPollingWindow = Boolean(
        pollingStartedAt && Date.now() - pollingStartedAt < WHATSAPP_BATCH_POLL_LIMIT_MS,
      );
      return (query.state.data?.queued ?? 1) > 0 && stillWithinPollingWindow ? 2_000 : false;
    },
  });
}

export function usePreviewWhatsAppMessage() {
  return useMutation({
    mutationFn: ({
      groupId,
      draft,
    }: {
      groupId: string;
      draft: Parameters<typeof whatsappApi.previewMessage>[1];
    }) => whatsappApi.previewMessage(groupId, draft),
  });
}

export function useSendWhatsAppWelcome() {
  return useMutation({
    mutationFn: ({ groupId, messageContent }: { groupId: string; messageContent: string }) =>
      whatsappApi.sendWelcome(groupId, messageContent),
  });
}

export function useSendWhatsAppPassportLink() {
  return useMutation({
    mutationFn: ({
      groupId,
      passportLink,
      messageContent,
    }: {
      groupId: string;
      passportLink: string;
      messageContent: string;
    }) => whatsappApi.sendPassportLink(groupId, passportLink, messageContent),
  });
}

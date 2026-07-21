import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { WhatsAppBroadcastGroupDetail } from "../api/whatsapp.api";
import { whatsappApi } from "../api/whatsapp.api";

export const WHATSAPP_QUERY_KEYS = {
  groups: ["whatsapp", "groups"] as const,
  group: (groupId: string) => ["whatsapp", "groups", groupId] as const,
  rejectedContacts: (groupId: string) =>
    ["whatsapp", "groups", groupId, "rejected-contacts"] as const,
  rejectedContactsPage: (groupId: string, limit: number, offset: number) =>
    [
      ...WHATSAPP_QUERY_KEYS.rejectedContacts(groupId),
      { limit, offset },
    ] as const,
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
    refetchInterval: (query) => (
      query.state.data?.recipients.some((recipient) =>
        recipient.message_statuses.some(
          (status) =>
            status.resend_blocked
            && (
              status.latest_resend_status === "queued"
              || status.latest_resend_status === "processing"
            ),
        ),
      )
        ? 2_000
        : false
    ),
  });
}

export function useWhatsAppRejectedContacts({
  groupId,
  enabled,
  limit,
  offset,
}: {
  groupId: string;
  enabled: boolean;
  limit: number;
  offset: number;
}) {
  return useQuery({
    queryKey: WHATSAPP_QUERY_KEYS.rejectedContactsPage(
      groupId,
      limit,
      offset,
    ),
    queryFn: () => whatsappApi.rejectedContacts({ groupId, limit, offset }),
    enabled,
  });
}

export function useResolveWhatsAppRejectedContact() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: whatsappApi.resolveRejectedContact,
    onSuccess: async (group) => {
      queryClient.setQueryData(WHATSAPP_QUERY_KEYS.group(group.id), group);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: WHATSAPP_QUERY_KEYS.groups }),
        queryClient.invalidateQueries({
          queryKey: WHATSAPP_QUERY_KEYS.rejectedContacts(group.id),
        }),
      ]);
    },
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
      queryClient.invalidateQueries({
        queryKey: WHATSAPP_QUERY_KEYS.rejectedContacts(group.id),
      });
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

export function useUpdateWhatsAppRecipientPhone() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: whatsappApi.updateRecipientPhone,
    onSuccess: (group) => {
      queryClient.setQueryData(
        WHATSAPP_QUERY_KEYS.group(group.id),
        group,
      );
      queryClient.invalidateQueries({ queryKey: WHATSAPP_QUERY_KEYS.groups });
    },
  });
}

export function useResendWhatsAppRecipientMessage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: whatsappApi.resendRecipientMessage,
    onSuccess: async (_, { groupId }) => {
      await queryClient.invalidateQueries({
        queryKey: WHATSAPP_QUERY_KEYS.group(groupId),
      });
      await queryClient.invalidateQueries({
        queryKey: WHATSAPP_QUERY_KEYS.groups,
      });
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
      signal,
    }: {
      groupId: string;
      draft: Parameters<typeof whatsappApi.previewMessage>[1];
      signal?: AbortSignal;
    }) => whatsappApi.previewMessage(groupId, draft, signal),
  });
}

export function useSendWhatsAppWelcome() {
  return useMutation({
    mutationFn: ({
      groupId,
      messageContent,
      image,
      headerImageId,
      recipientIds,
    }: {
      groupId: string;
      messageContent: string;
      image: File | null;
      headerImageId: string | null;
      recipientIds: string[] | null;
    }) => whatsappApi.sendWelcome(
      groupId,
      messageContent,
      image,
      headerImageId,
      recipientIds,
    ),
  });
}

export function useSendWhatsAppPassportLink() {
  return useMutation({
    mutationFn: ({
      groupId,
      passportIntro,
      passportLink,
      messageContent,
      image,
      headerImageId,
      recipientIds,
      supportContactIds,
    }: {
      groupId: string;
      passportIntro: string;
      passportLink: string;
      messageContent: string;
      image: File | null;
      headerImageId: string | null;
      recipientIds: string[] | null;
      supportContactIds: string[] | null;
    }) => whatsappApi.sendPassportLink(
      groupId,
      passportIntro,
      passportLink,
      messageContent,
      image,
      headerImageId,
      recipientIds,
      supportContactIds,
    ),
  });
}

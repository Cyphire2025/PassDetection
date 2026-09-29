import { useNormalWhatsAppSend } from "./use-normal-send";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  WhatsAppBroadcastGroupDetail,
  WhatsAppReminderAudience,
} from "../api/whatsapp.api";
import { whatsappApi } from "../api/whatsapp.api";
import {
  type CreateWhatsAppGroupInput,
  whatsappSourceGroupsApi,
} from "../api/whatsapp-source-groups.api";
import {
  isMissingWhatsAppBatchStatus,
  shouldRetryWhatsAppBatchStatus,
  whatsappBatchHttpStatus,
  whatsappBatchPollInterval,
  whatsappRecipientPollInterval,
} from "../utils/batch-polling";

export const WHATSAPP_QUERY_KEYS = {
  // This prefix also refreshes details, recipient/rejected rosters and source
  // contacts. Do not invalidate its children again for the same mutation.
  groups: ["whatsapp", "groups"] as const,
  groupList: (archived: boolean) => ["whatsapp", "groups", { archived }] as const,
  group: (groupId: string) => ["whatsapp", "groups", groupId] as const,
  rejectedContacts: (groupId: string) =>
    ["whatsapp", "groups", groupId, "rejected-contacts"] as const,
  recipientRoster: (groupId: string) =>
    ["whatsapp", "groups", groupId, "recipient-roster"] as const,
  rejectedContactsPage: (groupId: string, limit: number, offset: number) =>
    [
      ...WHATSAPP_QUERY_KEYS.rejectedContacts(groupId),
      { limit, offset },
    ] as const,
};

export function useWhatsAppGroups(archived = false) {
  return useQuery({
    queryKey: WHATSAPP_QUERY_KEYS.groupList(archived),
    queryFn: ({ signal }) => whatsappApi.groups(archived, signal),
  });
}

function useWhatsAppArchiveMutation(restore: boolean) {
  const queryClient = useQueryClient();
  return useMutation({
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

export function useWhatsAppGroup(groupId: string | null) {
  return useQuery({
    queryKey: groupId ? WHATSAPP_QUERY_KEYS.group(groupId) : ["whatsapp", "groups", "none"],
    queryFn: ({ signal }) => whatsappApi.group(groupId as string, signal),
    enabled: Boolean(groupId),
    refetchOnMount: "always",
    refetchInterval: (query) => whatsappRecipientPollInterval(query.state.data?.recipients ?? []),
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
  });
}

export function useWhatsAppRecipientRoster(groupId: string | null) {
  return useQuery({
    queryKey: groupId
      ? WHATSAPP_QUERY_KEYS.recipientRoster(groupId)
      : ["whatsapp", "groups", "none", "recipient-roster"],
    queryFn: ({ signal }) => whatsappApi.recipientRoster(groupId as string, signal),
    enabled: Boolean(groupId),
    refetchInterval: (query) => whatsappRecipientPollInterval(
      query.state.data?.items.flatMap((item) => item.kind === "recipient" ? [item.recipient] : []) ?? [],
    ),
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
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
    queryFn: ({ signal }) => whatsappApi.rejectedContacts({ groupId, limit, offset, signal }),
    enabled,
  });
}

export function useResolveWhatsAppRejectedContact() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: whatsappApi.resolveRejectedContact,
    onSuccess: async (group) => {
      queryClient.setQueryData(WHATSAPP_QUERY_KEYS.group(group.id), group);
      await queryClient.invalidateQueries({ queryKey: WHATSAPP_QUERY_KEYS.groups });
    },
  });
}

export function useRestoreWhatsAppReplacedRecipient() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      clientGroupId,
      resolutionId,
    }: {
      broadcastGroupId: string;
      clientGroupId: string;
      resolutionId: string;
    }) => whatsappApi.restoreReplacedRecipient({
      clientGroupId,
      resolutionId,
    }),
    onSettled: async (_data, _error, variables) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["whatsapp"] }),
        queryClient.invalidateQueries({
          queryKey: [
            "upload-links",
            variables.clientGroupId,
            "whatsapp-matches",
          ],
        }),
        queryClient.invalidateQueries({
          queryKey: [
            "upload-links",
            variables.clientGroupId,
            "replacement-candidates",
          ],
        }),
        queryClient.invalidateQueries({
          queryKey: ["passport-export-history", variables.clientGroupId],
        }),
      ]);
    },
  });
}

export function useCreateWhatsAppGroup() {
  const queryClient = useQueryClient();
  return useMutation({
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
              total_contact_count: Math.max(
                0,
                current.total_contact_count - 1,
              ),
              recipients: current.recipients.filter(
                (recipient) => recipient.id !== recipientId,
              ),
            }
          : current,
      );
      queryClient.invalidateQueries({ queryKey: WHATSAPP_QUERY_KEYS.groups });
    },
  });
}

export function useUpdateWhatsAppRecipientPhone() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: whatsappApi.updateRecipientPhone,
    onSuccess: async (group) => {
      queryClient.setQueryData(
        WHATSAPP_QUERY_KEYS.group(group.id),
        group,
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: WHATSAPP_QUERY_KEYS.groups }),
        queryClient.invalidateQueries({ queryKey: ["document-distribution", "delivery-preview"] }),
        queryClient.invalidateQueries({ queryKey: ["document-distribution", "delivery-tracking"] }),
      ]);
    },
  });
}

export function useUpdateWhatsAppRecipientDetails() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: whatsappApi.updateRecipientDetails,
    retry: false,
    onSuccess: async (group) => {
      queryClient.setQueryData(WHATSAPP_QUERY_KEYS.group(group.id), group);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: WHATSAPP_QUERY_KEYS.groups }),
        queryClient.invalidateQueries({ queryKey: ["document-distribution"] }),
      ]);
    },
  });
}

export function useResendWhatsAppRecipientMessage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: whatsappApi.resendRecipientMessage,
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: WHATSAPP_QUERY_KEYS.groups,
      });
    },
  });
}

export function useResendWhatsAppRecipientsMessage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: whatsappApi.resendRecipientsMessage,
    retry: false,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: WHATSAPP_QUERY_KEYS.groups });
    },
  });
}

function whatsappBatchErrorStatus(error: unknown): number | undefined {
  return whatsappBatchHttpStatus(error);
}

export function isMissingWhatsAppBatchError(error: unknown): boolean {
  return isMissingWhatsAppBatchStatus(whatsappBatchErrorStatus(error));
}

export function useWhatsAppBatchStatus(
  batchId: string | null,
  batchStartedAt: number | null,
  onMissingBatch?: (batchId: string) => void,
) {
  return useQuery({
    queryKey: ["whatsapp", "batches", batchId],
    queryFn: async ({ signal }) => {
      try {
        return await whatsappApi.batchSummary(batchId as string, signal);
      } catch (error) {
        if (batchId && isMissingWhatsAppBatchError(error)) {
          onMissingBatch?.(batchId);
        }
        throw error;
      }
    },
    enabled: Boolean(batchId),
    retry: (failureCount, error) =>
      shouldRetryWhatsAppBatchStatus(
        failureCount,
        whatsappBatchErrorStatus(error),
      ),
    refetchInterval: (query) => {
      if (isMissingWhatsAppBatchError(query.state.error)) return false;
      return whatsappBatchPollInterval(
        query.state.data?.queued,
        batchStartedAt,
      );
    },
  });
}

export function usePreviewWhatsAppBulkResendMessage() {
  return useMutation({
    mutationFn: whatsappApi.previewRecipientsResend,
    retry: false,
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
  return useNormalWhatsAppSend("welcome", ({
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
    }, intent) => whatsappApi.sendWelcome(
      intent,
      groupId,
      messageContent,
      image,
      headerImageId,
      recipientIds,
    ));
}

export function useSendWhatsAppReminder() {
  return useNormalWhatsAppSend("reminder", ({
      groupId,
      messageContent,
      recipientIds,
      audience,
      audienceClientGroupId,
    }: {
      groupId: string;
      messageContent: string;
      recipientIds: string[] | null;
      audience: WhatsAppReminderAudience;
      audienceClientGroupId: string | null;
    }, intent) => whatsappApi.sendReminder(
      intent,
      groupId,
      messageContent,
      recipientIds,
      audience,
      audienceClientGroupId,
    ));
}

export function useSendWhatsAppPassportLink() {
  return useNormalWhatsAppSend("passport_link", ({
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
    }, intent) => whatsappApi.sendPassportLink(
      intent,
      groupId,
      passportIntro,
      passportLink,
      messageContent,
      image,
      headerImageId,
      recipientIds,
      supportContactIds,
    ));
}

export function useSendWhatsAppGroupInvite() {
  return useNormalWhatsAppSend("group_invite", (variables: Omit<Parameters<typeof whatsappApi.sendGroupInvite>[0], "intent">, intent) =>
    whatsappApi.sendGroupInvite({ ...variables, intent }));
}

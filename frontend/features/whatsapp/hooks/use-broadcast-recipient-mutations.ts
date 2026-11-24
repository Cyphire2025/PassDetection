"use client";

import { useQueryClient } from "@tanstack/react-query";
import { usePrivateMutation } from "@/hooks/use-private-mutation";
import { whatsappApi, type WhatsAppBroadcastGroupDetail } from "../api/whatsapp.api";
import { WHATSAPP_QUERY_KEYS } from "./whatsapp-query-keys";

export function useResolveWhatsAppRejectedContact() {
  const queryClient = useQueryClient();
  return usePrivateMutation({
    mutationFn: whatsappApi.resolveRejectedContact,
    onSuccess: async (group) => {
      queryClient.setQueryData(WHATSAPP_QUERY_KEYS.group(group.id), group);
      await queryClient.invalidateQueries({ queryKey: WHATSAPP_QUERY_KEYS.groups });
    },
  });
}

export function useRestoreWhatsAppReplacedRecipient() {
  const queryClient = useQueryClient();
  return usePrivateMutation({
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

export function useAddWhatsAppRecipients() {
  const queryClient = useQueryClient();
  return usePrivateMutation({
    mutationFn: whatsappApi.addRecipients,
    onSuccess: (group) => {
      queryClient.setQueryData(WHATSAPP_QUERY_KEYS.group(group.id), group);
      queryClient.invalidateQueries({ queryKey: WHATSAPP_QUERY_KEYS.groups });
    },
  });
}

export function useDeleteWhatsAppRecipient() {
  const queryClient = useQueryClient();
  return usePrivateMutation({
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
  return usePrivateMutation({
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
  return usePrivateMutation({
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

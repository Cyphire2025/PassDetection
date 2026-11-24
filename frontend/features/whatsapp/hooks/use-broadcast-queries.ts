"use client";

import { useQuery } from "@tanstack/react-query";
import { whatsappApi } from "../api/whatsapp.api";
import { whatsappRecipientPollInterval } from "../utils/batch-polling";
import { WHATSAPP_QUERY_KEYS } from "./whatsapp-query-keys";

export function useWhatsAppGroups(archived = false) {
  return useQuery({
    queryKey: WHATSAPP_QUERY_KEYS.groupList(archived),
    queryFn: ({ signal }) => whatsappApi.groups(archived, signal),
  });
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

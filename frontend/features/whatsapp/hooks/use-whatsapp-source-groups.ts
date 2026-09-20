import { useQuery } from "@tanstack/react-query";
import { whatsappSourceGroupsApi } from "../api/whatsapp-source-groups.api";
import { WHATSAPP_SOURCE_QUERY_KEYS } from "../utils/source-group-cache";

export function useWhatsAppSourceGroups() {
  return useQuery({
    queryKey: WHATSAPP_SOURCE_QUERY_KEYS.groups,
    queryFn: ({ signal }) => whatsappSourceGroupsApi.list(signal),
    // Do not inherit the application's five-minute freshness window: this
    // picker must reflect newly created groups whenever it opens.
    staleTime: 0,
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
    refetchOnReconnect: "always",
  });
}

export function useWhatsAppSourceGroupPreview(groupId: string) {
  return useQuery({
    queryKey: WHATSAPP_SOURCE_QUERY_KEYS.preview(groupId),
    queryFn: ({ signal }) => whatsappSourceGroupsApi.preview(groupId, signal),
    enabled: Boolean(groupId),
    staleTime: 0,
    refetchOnWindowFocus: true,
    refetchOnReconnect: "always",
    refetchOnMount: "always",
    retry: false,
  });
}

export function useWhatsAppBroadcastSourceContacts(groupId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["whatsapp", "groups", groupId, "source-contacts"],
    queryFn: ({ signal }) => whatsappSourceGroupsApi.groupContacts(groupId, signal),
    enabled,
    staleTime: 0,
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
    refetchOnReconnect: "always",
  });
}

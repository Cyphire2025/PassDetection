import { useQuery } from "@tanstack/react-query";
import { whatsappSourceGroupsApi } from "../api/whatsapp-source-groups.api";

export function useWhatsAppSourceGroups() {
  return useQuery({
    queryKey: ["whatsapp", "source-groups"],
    queryFn: ({ signal }) => whatsappSourceGroupsApi.list(signal),
    refetchOnWindowFocus: false,
  });
}

export function useWhatsAppSourceGroupPreview(groupId: string) {
  return useQuery({
    queryKey: ["whatsapp", "source-group-preview", groupId],
    queryFn: ({ signal }) => whatsappSourceGroupsApi.preview(groupId, signal),
    enabled: Boolean(groupId),
    refetchOnWindowFocus: false,
    refetchOnMount: "always",
    retry: false,
  });
}

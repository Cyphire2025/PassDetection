import type { QueryClient } from "@tanstack/react-query";

export const WHATSAPP_SOURCE_QUERY_KEYS = {
  groups: ["whatsapp", "source-groups"] as const,
  previews: ["whatsapp", "source-group-preview"] as const,
  preview: (groupId: string) => ["whatsapp", "source-group-preview", groupId] as const,
};

/** Passport mutations change both the group picker and its contact snapshot. */
export function invalidateWhatsAppSourceGroups(queryClient: QueryClient, groupId?: string) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: WHATSAPP_SOURCE_QUERY_KEYS.groups }),
    queryClient.invalidateQueries({
      queryKey: groupId ? WHATSAPP_SOURCE_QUERY_KEYS.preview(groupId) : WHATSAPP_SOURCE_QUERY_KEYS.previews,
    }),
    // Linked broadcasts synchronize their delivery destinations from this roster.
    queryClient.invalidateQueries({ queryKey: ["whatsapp", "groups"] }),
  ]);
}

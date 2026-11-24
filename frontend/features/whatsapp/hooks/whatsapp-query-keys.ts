export const WHATSAPP_QUERY_KEYS = {
  groups: ["whatsapp", "groups"] as const,
  groupList: (archived: boolean) => ["whatsapp", "groups", { archived }] as const,
  group: (groupId: string) => ["whatsapp", "groups", groupId] as const,
  recipientRoster: (groupId: string) => ["whatsapp", "groups", groupId, "recipient-roster"] as const,
};

import { type GroupWhatsAppMatchesParams, type UploadLinkResponse } from "../api/upload-links.api";

export const uploadLinkQueryKeys = {
  all: ["upload-links"] as const,
  list: (statusFilter?: UploadLinkResponse["status"]) => ["upload-links", "list", statusFilter ?? "active-workflow"] as const,
  byToken: (token: string) => ["upload-links", "token", token] as const,
  whatsappLinks: (id: string) => ["upload-links", id, "whatsapp-links"] as const,
  whatsappBroadcastOptions: (id?: string) => (
    ["upload-links", id ?? "new", "whatsapp-broadcast-options"] as const
  ),
  whatsappMatches: (id: string, params: GroupWhatsAppMatchesParams) => (
    ["upload-links", id, "whatsapp-matches", params] as const
  ),
  replacementCandidates: (id: string) => (
    ["upload-links", id, "replacement-candidates"] as const
  ),
};

import { useQuery } from "@tanstack/react-query";
import type { DistributionDocumentType } from "@/types/document-distribution.types";
import { groupUpdatesApi } from "../api/group-updates.api";

export function useGroupUpdateAudience(groupId: string | undefined, documentType: DistributionDocumentType = "visa") {
  const audience = { submission_status: "all", document_status: "all", document_type: documentType } as const;
  return useQuery({
    queryKey: ["group-update-preview", groupId, audience],
    queryFn: ({ signal }) => groupUpdatesApi.preview(groupId!, audience, signal),
    enabled: Boolean(groupId), staleTime: 0,
    refetchInterval: query => query.state.data?.recipients.some(row => ["queued", "processing", "submitted", "sent", "delivered"].includes(row.latest_update_status ?? "")) ? 5000 : false,
  });
}

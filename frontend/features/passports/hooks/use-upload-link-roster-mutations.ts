import { usePrivateMutation } from "@/hooks/use-private-mutation";
import { useQueryClient } from "@tanstack/react-query";
import { invalidateWhatsAppSourceGroups } from "@/features/whatsapp/utils/source-group-cache";
import { uploadLinksApi } from "../api/upload-links.api";
import { uploadLinkQueryKeys as QUERY_KEYS } from "./upload-link-query-keys";

export function useUpdateGroupWhatsAppLinks(id: string) {
  const queryClient = useQueryClient();

  return usePrivateMutation({
    mutationFn: ({
      whatsappBroadcastGroupIds,
      matchingFieldsByBroadcast,
    }: {
      whatsappBroadcastGroupIds: string[];
      matchingFieldsByBroadcast: Record<string, string[]>;
    }, _context, owner) => (
      uploadLinksApi.updateWhatsAppLinks(
        id,
        whatsappBroadcastGroupIds,
        matchingFieldsByBroadcast, owner.requestConfig
      )
    ),
    onSuccess: (response) => {
      queryClient.setQueryData(QUERY_KEYS.whatsappLinks(id), response);
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.all });
      queryClient.invalidateQueries({ queryKey: ["whatsapp"] });
      queryClient.invalidateQueries({
        queryKey: ["upload-links", id, "whatsapp-matches"],
      });
      queryClient.invalidateQueries({
        queryKey: ["passport-export-fields", id],
      });
    },
  });
}

export function useResolveUnidentifiedReplacement(id: string) {
  const queryClient = useQueryClient();

  return usePrivateMutation({
    mutationFn: ({
      submissionId,
      recipientId,
      requestId,
    }: {
      submissionId: string;
      recipientId: string;
      requestId: string;
    }, _context, owner) => uploadLinksApi.resolveUnidentifiedReplacement(
      id,
      submissionId,
      recipientId,
      requestId, owner.requestConfig
    ),
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["upload-links", id, "whatsapp-matches"],
      });
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.replacementCandidates(id),
      });
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.whatsappLinks(id),
      });
      queryClient.invalidateQueries({
        queryKey: ["passport-export-history", id],
      });
      queryClient.invalidateQueries({ queryKey: ["whatsapp"] });
    },
  });
}

export function useRejectUnidentifiedUpload(id: string) {
  const queryClient = useQueryClient();

  return usePrivateMutation({
    mutationFn: ({
      submissionId,
      requestId,
    }: {
      submissionId: string;
      requestId: string;
    }, _context, owner) => uploadLinksApi.rejectUnidentifiedUpload(
      id,
      submissionId,
      requestId, owner.requestConfig
    ),
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["upload-links", id, "whatsapp-matches"],
      });
      queryClient.invalidateQueries({
        queryKey: ["passport-export-history", id],
      });
      return invalidateWhatsAppSourceGroups(queryClient, id);
    },
  });
}

export function useRestoreRosterResolution(id: string) {
  const queryClient = useQueryClient();

  return usePrivateMutation({
    mutationFn: (resolutionId: string, _context, owner) => (
      uploadLinksApi.restoreRosterResolution(id, resolutionId, owner.requestConfig)
    ),
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["upload-links", id, "whatsapp-matches"],
      });
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.replacementCandidates(id),
      });
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.whatsappLinks(id),
      });
      queryClient.invalidateQueries({
        queryKey: ["passport-export-history", id],
      });
      queryClient.invalidateQueries({ queryKey: ["whatsapp"] });
    },
  });
}

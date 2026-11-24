import { useQuery } from "@tanstack/react-query";
import { apiErrorStatus } from "@/lib/api/error-status";
import {
  uploadLinksApi,
  type GroupWhatsAppMatchesParams,
  type UploadLinkResponse,
} from "../api/upload-links.api";
import { uploadLinkQueryKeys as QUERY_KEYS } from "./upload-link-query-keys";

export function useUploadLinks(statusFilter?: UploadLinkResponse["status"], enabled = true) {
  return useQuery({
    queryKey: QUERY_KEYS.list(statusFilter),
    queryFn: () => uploadLinksApi.list(statusFilter),
    enabled,
  });
}

export function useUploadLinkByToken(token: string) {
  return useQuery({
    queryKey: QUERY_KEYS.byToken(token),
    queryFn: () => uploadLinksApi.getByToken(token),
    enabled: Boolean(token),
    retry: (failureCount, error) => {
      const status = apiErrorStatus(error);
      if (status && [400, 401, 403, 404, 410, 422].includes(status)) return false;
      return failureCount < 2;
    },
    retryDelay: (attemptIndex) => Math.min(2_000, 500 * (2 ** attemptIndex)),
  });
}

export function useGroupWhatsAppLinks(id: string, enabled = true) {
  return useQuery({
    queryKey: QUERY_KEYS.whatsappLinks(id),
    queryFn: () => uploadLinksApi.getWhatsAppLinks(id),
    enabled: enabled && Boolean(id),
    refetchInterval: 30_000,
  });
}

export function useWhatsAppBroadcastOptions(id?: string, enabled = true) {
  return useQuery({
    queryKey: QUERY_KEYS.whatsappBroadcastOptions(id),
    queryFn: () => uploadLinksApi.getWhatsAppBroadcastOptions(id),
    enabled,
  });
}

export function useGroupWhatsAppMatches(
  id: string,
  params: GroupWhatsAppMatchesParams,
  enabled = true,
) {
  return useQuery({
    queryKey: QUERY_KEYS.whatsappMatches(id, params),
    queryFn: () => uploadLinksApi.getWhatsAppMatches(id, params),
    enabled: enabled && Boolean(id),
    refetchInterval: 30_000,
  });
}

export function useReplacementCandidates(id: string, enabled = true) {
  return useQuery({
    queryKey: QUERY_KEYS.replacementCandidates(id),
    queryFn: () => uploadLinksApi.getReplacementCandidates(id),
    enabled: enabled && Boolean(id),
  });
}

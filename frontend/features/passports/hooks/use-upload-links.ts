/**
 * React Query Hooks for Upload Links
 */

import {
  useQuery,
  useMutation,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { QUERY_KEYS as APP_QUERY_KEYS } from "@/constants";
import {
  uploadLinksApi,
  type CreateUploadLinkRequest,
  type GroupWhatsAppMatchesParams,
  type UpdateUploadLinkRequest,
  type UploadLinkResponse,
} from "../api/upload-links.api";

const QUERY_KEYS = {
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

function invalidatePassportGroupQueries(
  queryClient: QueryClient,
  groupId?: string,
) {
  queryClient.invalidateQueries({
    queryKey: APP_QUERY_KEYS.passports.groups(),
    exact: true,
  });
  queryClient.invalidateQueries({
    queryKey: ["passports", "group-summaries"],
  });
  if (groupId) {
    queryClient.invalidateQueries({
      queryKey: ["passports", "group-summary", groupId],
    });
  }
}

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
      const status = isAxiosError(error) ? error.response?.status : undefined;
      if (status && [400, 401, 403, 404, 410, 422].includes(status)) return false;
      return failureCount < 2;
    },
    retryDelay: (attemptIndex) => Math.min(2_000, 500 * (2 ** attemptIndex)),
  });
}

export function useCreateUploadLink() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: CreateUploadLinkRequest) => uploadLinksApi.create(data),
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.all });
      invalidatePassportGroupQueries(queryClient, response.id);
    },
  });
}

export function useRevokeUploadLink() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => uploadLinksApi.revoke(id),
    onSuccess: (_response, id) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.all });
      invalidatePassportGroupQueries(queryClient, id);
    },
  });
}

export function useDeleteUploadLink() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => uploadLinksApi.delete(id),
    onSuccess: (_response, id) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.all });
      invalidatePassportGroupQueries(queryClient, id);
    },
  });
}

export function useUpdateUploadLink() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, ...data }: UpdateUploadLinkRequest & { id: string }) => uploadLinksApi.update(id, data),
    onSuccess: (_response, variables) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.all });
      invalidatePassportGroupQueries(queryClient, variables.id);
      queryClient.invalidateQueries({
        queryKey: ["passport-export-fields", variables.id],
      });
    },
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

export function useUpdateGroupWhatsAppLinks(id: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (whatsappBroadcastGroupIds: string[]) => (
      uploadLinksApi.updateWhatsAppLinks(id, whatsappBroadcastGroupIds)
    ),
    onSuccess: (response) => {
      queryClient.setQueryData(QUERY_KEYS.whatsappLinks(id), response);
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.all });
      queryClient.invalidateQueries({
        queryKey: ["upload-links", id, "whatsapp-matches"],
      });
      queryClient.invalidateQueries({
        queryKey: ["passport-export-fields", id],
      });
    },
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

export function useResolveUnidentifiedReplacement(id: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      submissionId,
      recipientId,
      requestId,
    }: {
      submissionId: string;
      recipientId: string;
      requestId: string;
    }) => uploadLinksApi.resolveUnidentifiedReplacement(
      id,
      submissionId,
      recipientId,
      requestId,
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

  return useMutation({
    mutationFn: ({
      submissionId,
      requestId,
    }: {
      submissionId: string;
      requestId: string;
    }) => uploadLinksApi.rejectUnidentifiedUpload(
      id,
      submissionId,
      requestId,
    ),
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["upload-links", id, "whatsapp-matches"],
      });
      queryClient.invalidateQueries({
        queryKey: ["passport-export-history", id],
      });
    },
  });
}

export function useRestoreRosterResolution(id: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (resolutionId: string) => (
      uploadLinksApi.restoreRosterResolution(id, resolutionId)
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

export function usePermanentlyDeleteUploadLink() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, retainRecords }: { id: string; retainRecords: boolean }) =>
      uploadLinksApi.permanentDelete(id, retainRecords),
    onSuccess: (_response, variables) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.all });
      invalidatePassportGroupQueries(queryClient, variables.id);
    },
  });
}

export function useRestoreUploadLink() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => uploadLinksApi.restore(id),
    onSuccess: (_response, id) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.all });
      invalidatePassportGroupQueries(queryClient, id);
    },
  });
}

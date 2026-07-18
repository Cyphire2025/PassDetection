/**
 * React Query Hooks for Upload Links
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { uploadLinksApi, type CreateUploadLinkRequest, type UploadLinkResponse } from "../api/upload-links.api";

const QUERY_KEYS = {
  all: ["upload-links"] as const,
  list: (statusFilter?: UploadLinkResponse["status"]) => ["upload-links", "list", statusFilter ?? "active-workflow"] as const,
  byToken: (token: string) => ["upload-links", "token", token] as const,
};

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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.all });
    },
  });
}

export function useRevokeUploadLink() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => uploadLinksApi.revoke(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.all });
    },
  });
}

export function useDeleteUploadLink() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => uploadLinksApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.all });
    },
  });
}

export function useUpdateUploadLink() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, ...data }: CreateUploadLinkRequest & { id: string }) => uploadLinksApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.all });
    },
  });
}

export function usePermanentlyDeleteUploadLink() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, retainRecords }: { id: string; retainRecords: boolean }) =>
      uploadLinksApi.permanentDelete(id, retainRecords),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.all });
    },
  });
}

export function useRestoreUploadLink() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => uploadLinksApi.restore(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.all });
    },
  });
}

import { usePrivateMutation } from "@/hooks/use-private-mutation";
import { useQueryClient } from "@tanstack/react-query";
import { QUERY_KEYS as DASHBOARD_QUERY_KEYS } from "@/constants";
import type { PassportGroupSummary } from "@/types/passport.types";
import { invalidateWhatsAppSourceGroups } from "@/features/whatsapp/utils/source-group-cache";
import {
  uploadLinksApi,
  type CreateUploadLinkRequest,
  type UpdateUploadLinkRequest,
} from "../api/upload-links.api";
import { uploadLinkQueryKeys as QUERY_KEYS } from "./upload-link-query-keys";

export function useCreateUploadLink() {
  const queryClient = useQueryClient();

  return usePrivateMutation({
    mutationFn: (data: CreateUploadLinkRequest, _context, owner) => uploadLinksApi.create(data, owner.requestConfig),
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.all });
      queryClient.invalidateQueries({ queryKey: DASHBOARD_QUERY_KEYS.passports.groups() });
      return invalidateWhatsAppSourceGroups(queryClient, response.id);
    },
  });
}

export function useRevokeUploadLink() {
  const queryClient = useQueryClient();

  return usePrivateMutation({
    mutationFn: (id: string, _context, owner) => uploadLinksApi.revoke(id, owner.requestConfig),
    onSuccess: (_response, id) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.all });
      return invalidateWhatsAppSourceGroups(queryClient, id);
    },
  });
}

export function useDeleteUploadLink() {
  const queryClient = useQueryClient();

  return usePrivateMutation({
    mutationFn: (id: string, _context, owner) => uploadLinksApi.delete(id, owner.requestConfig),
    onSuccess: (_response, id) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.all });
      return invalidateWhatsAppSourceGroups(queryClient, id);
    },
  });
}

export function useUpdateUploadLink() {
  const queryClient = useQueryClient();

  return usePrivateMutation({
    mutationFn: ({ id, ...data }: UpdateUploadLinkRequest & { id: string }, _context, owner) => uploadLinksApi.update(id, data, owner.requestConfig),
    onSuccess: async (response, variables) => {
      // Trip editing reads the group summary cache. Merge the saved response
      // immediately so reopening the dialog cannot restore stale controls.
      queryClient.setQueryData<PassportGroupSummary[]>(
        DASHBOARD_QUERY_KEYS.passports.groups(),
        (groups) => groups?.map((group) => group.group_id === response.id ? {
          ...group,
          ...response,
          group_name: response.name,
          group_status: response.status === "deleted" ? group.group_status : response.status,
        } : group),
      );
      await Promise.all([
        invalidateWhatsAppSourceGroups(queryClient, variables.id),
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.all }),
        queryClient.invalidateQueries({ queryKey: DASHBOARD_QUERY_KEYS.passports.groups() }),
        queryClient.invalidateQueries({ queryKey: ["passport-export-fields", variables.id] }),
        ...(variables.matching_fields_by_broadcast !== undefined || variables.whatsapp_broadcast_group_ids !== undefined
          ? [queryClient.invalidateQueries({ queryKey: ["whatsapp"] })]
          : []),
      ]);
    },
  });
}

export function usePermanentlyDeleteUploadLink() {
  const queryClient = useQueryClient();

  return usePrivateMutation({
    mutationFn: ({ id, retainRecords }: { id: string; retainRecords: boolean }, _context, owner) =>
      uploadLinksApi.permanentDelete(id, retainRecords, owner.requestConfig),
    onSuccess: (_response, variables) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.all });
      return invalidateWhatsAppSourceGroups(queryClient, variables.id);
    },
  });
}

export function useRestoreUploadLink() {
  const queryClient = useQueryClient();

  return usePrivateMutation({
    mutationFn: (id: string, _context, owner) => uploadLinksApi.restore(id, owner.requestConfig),
    onSuccess: (_response, id) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.all });
      return invalidateWhatsAppSourceGroups(queryClient, id);
    },
  });
}

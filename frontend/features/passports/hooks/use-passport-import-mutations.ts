import { usePrivateMutation } from "@/hooks/use-private-mutation";
import { useQueryClient } from "@tanstack/react-query";
import { QUERY_KEYS } from "@/constants";
import { invalidateWhatsAppSourceGroups } from "@/features/whatsapp/utils/source-group-cache";
import { passportsApi } from "../api/passports.api";
import type { PassportDocumentImportChunkRequest, PassportDocumentImportRequest } from "../api/passports.api";

export function useImportPassportGroup(groupId: string) {
  const queryClient = useQueryClient();

  return usePrivateMutation({
    mutationFn: (file: File, _context, owner) => passportsApi.importGroup(groupId, file, owner.requestConfig),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.passports.all });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.dashboard.stats });
      return invalidateWhatsAppSourceGroups(queryClient, groupId);
    },
  });
}

export function usePreviewPassportDocuments(groupId: string) {
  return usePrivateMutation({ mutationFn: (request: PassportDocumentImportRequest, _context, owner) => passportsApi.previewPassportDocuments(groupId, request, owner.requestConfig) });
}

export function useSavePassportDocuments(groupId: string) {
  const queryClient = useQueryClient();
  return usePrivateMutation({
    mutationFn: (request: PassportDocumentImportChunkRequest, _context, owner) => passportsApi.savePassportDocumentsInChunks(groupId, request, owner.requestConfig),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.passports.all });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.passports.groupDetail(groupId, {}) });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.dashboard.stats });
    },
    // A later chunk can fail after earlier records have already been saved.
    onSettled: () => invalidateWhatsAppSourceGroups(queryClient, groupId),
  });
}

import { usePrivateMutation } from "@/hooks/use-private-mutation";
import { useQueryClient } from "@tanstack/react-query";
import { QUERY_KEYS } from "@/constants";
import { invalidateWhatsAppSourceGroups } from "@/features/whatsapp/utils/source-group-cache";
import { passportsApi } from "../api/passports.api";
import type { BulkStaffApprovePassportSelection } from "../api/passports.api";

export function useBulkDocumentFollowUp(groupId: string) {
  const queryClient = useQueryClient();
  return usePrivateMutation({
    mutationFn: (request: { submission_ids: string[]; flagged: boolean }, _context, owner) =>
      passportsApi.bulkDocumentFollowUp(groupId, request, owner.requestConfig),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: QUERY_KEYS.passports.all }),
  });
}

export function useBulkDeletePassportSubmissions(groupId: string) {
  const queryClient = useQueryClient();

  return usePrivateMutation({
    mutationFn: (submissionIds: string[], _context, owner) => (
      passportsApi.bulkDelete(groupId, submissionIds, owner.requestConfig)
    ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.passports.all });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.dashboard.stats });
      return invalidateWhatsAppSourceGroups(queryClient, groupId);
    },
  });
}

export function useBulkStaffApprovePassportSubmissions(groupId: string) {
  const queryClient = useQueryClient();

  return usePrivateMutation({
    mutationFn: (submissions: BulkStaffApprovePassportSelection[], _context, owner) => (
      passportsApi.bulkStaffApprove(groupId, submissions, owner.requestConfig)
    ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.passports.all });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.dashboard.stats });
      return invalidateWhatsAppSourceGroups(queryClient, groupId);
    },
  });
}

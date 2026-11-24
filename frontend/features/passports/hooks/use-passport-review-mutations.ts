import { usePrivateMutation } from "@/hooks/use-private-mutation";
import { useQueryClient } from "@tanstack/react-query";
import { QUERY_KEYS } from "@/constants";
import { invalidateWhatsAppSourceGroups } from "@/features/whatsapp/utils/source-group-cache";
import type { StaffApprovalRequest } from "@/types/passport.types";
import { passportsApi } from "../api/passports.api";
import { getStaffApprovalErrorFeedback } from "../utils/passport-review";

export function useConfirmPassportSubmission(id: string) {
  const queryClient = useQueryClient();

  return usePrivateMutation({
    mutationFn: (confirmedFields: Record<string, string>, _context, owner) => passportsApi.confirm(id, confirmedFields, owner.requestConfig),
    onSuccess: (updated) => {
      queryClient.setQueryData(QUERY_KEYS.passports.detail(id), updated);
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.passports.all });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.dashboard.stats });
      return invalidateWhatsAppSourceGroups(queryClient, updated.group_id);
    },
  });
}

export function useStaffApprovePassportSubmission(id: string) {
  const queryClient = useQueryClient();

  return usePrivateMutation({
    mutationFn: (request: StaffApprovalRequest, _context, owner) => (
      passportsApi.staffApprove(id, request, owner.requestConfig)
    ),
    onSuccess: (result) => {
      queryClient.setQueryData(
        QUERY_KEYS.passports.detail(id),
        result.submission,
      );
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.passports.detail(id),
      });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.passports.all });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.dashboard.stats });
      return invalidateWhatsAppSourceGroups(queryClient, result.submission.group_id);
    },
    onError: (error) => {
      const feedback = getStaffApprovalErrorFeedback(error);
      if (
        feedback.kind === "record_changed"
        || feedback.kind === "unavailable"
      ) {
        queryClient.invalidateQueries({
          queryKey: QUERY_KEYS.passports.detail(id),
        });
      }
    },
  });
}

export function useRetryPassportAiVerification(id: string) {
  const queryClient = useQueryClient();

  return usePrivateMutation({
    mutationFn: (_variables, _context, owner) => passportsApi.retryAiVerification(id, owner.requestConfig),
    onSuccess: (updated) => {
      queryClient.setQueryData(QUERY_KEYS.passports.detail(id), updated);
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.passports.all });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.dashboard.stats });
      return invalidateWhatsAppSourceGroups(queryClient, updated.group_id);
    },
  });
}

export function useReextractPassportSubmission() {
  const queryClient = useQueryClient();

  return usePrivateMutation({
    mutationFn: (id: string, _context, owner) => passportsApi.reextract(id, {
      onProgress: (updated) => {
        owner.assertCurrent();
        queryClient.setQueryData(QUERY_KEYS.passports.detail(updated.id), updated);
      },
    }, owner.requestConfig),
    onSuccess: ({ submission: updated }) => {
      queryClient.setQueryData(QUERY_KEYS.passports.detail(updated.id), updated);
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.passports.all });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.dashboard.stats });
      return invalidateWhatsAppSourceGroups(queryClient, updated.group_id);
    },
  });
}

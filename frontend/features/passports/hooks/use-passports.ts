import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { QUERY_KEYS } from "@/constants";
import type { StaffApprovalRequest } from "@/types/passport.types";
import { passportsApi } from "../api/passports.api";
import type { PassportDocumentImportChunkRequest, PassportDocumentImportRequest } from "../api/passports.api";
import { getStaffApprovalErrorFeedback } from "../utils/passport-review";
import { isPassportWorkflowPending } from "../utils/passport-workflow";

export function usePassports() {
  return useQuery({
    queryKey: QUERY_KEYS.passports.list(),
    queryFn: () => passportsApi.list(),
    refetchInterval: 30_000,
  });
}

export function usePassportGroups() {
  return useQuery({
    queryKey: QUERY_KEYS.passports.groups(),
    queryFn: () => passportsApi.listGroups(),
    refetchInterval: 30_000,
  });
}

export function usePassportsByGroup(groupId: string, search?: string, includeDeleted = false) {
  return useQuery({
    queryKey: QUERY_KEYS.passports.groupDetail(groupId, { search, includeDeleted }),
    queryFn: () => passportsApi.listByGroup(groupId, search, includeDeleted),
    enabled: Boolean(groupId),
    refetchInterval: (query) => (
      query.state.data?.some((passport) => (
        isPassportWorkflowPending(passport.status, passport.extraction_status)
      ))
        ? 2_000
        : 30_000
    ),
  });
}

export function useExportPassportGroup() {
  return useMutation({
    mutationFn: (groupId: string) => passportsApi.exportGroup(groupId),
  });
}

export function useExportPassportGroupImages() {
  return useMutation({
    mutationFn: (groupId: string) => passportsApi.exportGroupImages(groupId),
  });
}

export function useImportPassportGroup(groupId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (file: File) => passportsApi.importGroup(groupId, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.passports.all });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.dashboard.stats });
    },
  });
}

export function usePreviewPassportDocuments(groupId: string) {
  return useMutation({ mutationFn: (request: PassportDocumentImportRequest) => passportsApi.previewPassportDocuments(groupId, request) });
}

export function useSavePassportDocuments(groupId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: PassportDocumentImportChunkRequest) => passportsApi.savePassportDocumentsInChunks(groupId, request),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.passports.all });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.passports.groupDetail(groupId, {}) });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.dashboard.stats });
    },
  });
}

export function useExportSelectedPassports() {
  return useMutation({
    mutationFn: (submissionIds: string[]) => passportsApi.exportSelectedPassports(submissionIds),
  });
}

export function useExportSelectedGroups() {
  return useMutation({
    mutationFn: (groupIds: string[]) => passportsApi.exportSelectedGroups(groupIds),
  });
}

export function usePassportSubmission(id: string) {
  return useQuery({
    queryKey: QUERY_KEYS.passports.detail(id),
    queryFn: () => passportsApi.getById(id),
    enabled: Boolean(id),
    refetchInterval: (query) => (
      isPassportWorkflowPending(
        query.state.data?.status,
        query.state.data?.extraction_status,
      )
        ? 2_000
        : false
    ),
  });
}

export function useConfirmPassportSubmission(id: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (confirmedFields: Record<string, string>) => passportsApi.confirm(id, confirmedFields),
    onSuccess: (updated) => {
      queryClient.setQueryData(QUERY_KEYS.passports.detail(id), updated);
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.passports.all });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.dashboard.stats });
    },
  });
}

export function useStaffApprovePassportSubmission(id: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (request: StaffApprovalRequest) => (
      passportsApi.staffApprove(id, request)
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

  return useMutation({
    mutationFn: () => passportsApi.retryAiVerification(id),
    onSuccess: (updated) => {
      queryClient.setQueryData(QUERY_KEYS.passports.detail(id), updated);
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.passports.all });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.dashboard.stats });
    },
  });
}

export function useReextractPassportSubmission() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => passportsApi.reextract(id, {
      onProgress: (updated) => {
        queryClient.setQueryData(QUERY_KEYS.passports.detail(updated.id), updated);
      },
    }),
    onSuccess: ({ submission: updated }) => {
      queryClient.setQueryData(QUERY_KEYS.passports.detail(updated.id), updated);
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.passports.all });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.dashboard.stats });
    },
  });
}

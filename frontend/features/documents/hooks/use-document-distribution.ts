import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { DistributionDocumentType } from "@/types/document-distribution.types";
import { documentDistributionApi } from "../api/document-distribution.api";

const documentKeys = {
  all: ["document-distribution"] as const,
  groups: () => ["document-distribution", "groups"] as const,
  review: (groupId: string, documentType: DistributionDocumentType) =>
    ["document-distribution", "groups", groupId, documentType] as const,
};

export function useDocumentGroups() {
  return useQuery({
    queryKey: documentKeys.groups(),
    queryFn: () => documentDistributionApi.listGroups(),
    refetchInterval: 30_000,
  });
}

export function useDocumentReview(groupId: string, documentType: DistributionDocumentType) {
  return useQuery({
    queryKey: documentKeys.review(groupId, documentType),
    queryFn: () => documentDistributionApi.getReview(groupId, documentType),
    enabled: Boolean(groupId && documentType),
  });
}

export function useUploadDistributionDocuments(groupId: string, documentType: DistributionDocumentType) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ files, onProgress }: { files: File[]; onProgress?: (progress: number) => void }) =>
      documentDistributionApi.uploadDocuments(groupId, documentType, files, onProgress),
    onSuccess: (data) => {
      queryClient.setQueryData(documentKeys.review(groupId, documentType), data);
      queryClient.invalidateQueries({ queryKey: documentKeys.groups() });
    },
  });
}

export function useVerifyDistributionDocuments(groupId: string, documentType: DistributionDocumentType) {
  return useMutation({
    mutationFn: (files: File[]) => documentDistributionApi.verifyDocuments(groupId, documentType, files),
  });
}

export function useReuploadPassengerDocument(groupId: string, documentType: DistributionDocumentType) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ passengerId, file }: { passengerId: string; file: File }) =>
      documentDistributionApi.reuploadPassengerDocument(groupId, documentType, passengerId, file),
    onSuccess: (data) => {
      queryClient.setQueryData(documentKeys.review(groupId, documentType), data);
      queryClient.invalidateQueries({ queryKey: documentKeys.groups() });
    },
  });
}

export function useDeleteDistributionDocuments(groupId: string, documentType: DistributionDocumentType) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (documentIds: string[]) => documentDistributionApi.deleteDocuments(groupId, documentType, documentIds),
    onSuccess: (data) => {
      queryClient.setQueryData(documentKeys.review(groupId, documentType), data);
      queryClient.invalidateQueries({ queryKey: documentKeys.groups() });
    },
  });
}

export function useSaveDocumentBatch(groupId: string, documentType: DistributionDocumentType) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (batchId: string) => documentDistributionApi.saveBatch(batchId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: documentKeys.review(groupId, documentType) });
    },
  });
}

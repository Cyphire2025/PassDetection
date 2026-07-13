import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { documentRenameApi } from "../api/document-rename.api";

const renameKeys = {
  batches: ["document-rename", "batches"] as const,
};

export function useRenameBatches() {
  return useQuery({
    queryKey: renameKeys.batches,
    queryFn: () => documentRenameApi.listBatches(),
  });
}

export function useAnalyzeRenameDocuments() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ title, files, onProgress }: { title: string; files: File[]; onProgress?: (progress: number) => void }) =>
      documentRenameApi.analyze(title, files, onProgress),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: renameKeys.batches });
    },
  });
}

export function useOpenRenameBatch() {
  return useMutation({
    mutationFn: (batchId: string) => documentRenameApi.getBatch(batchId),
  });
}

export function useDeleteRenameBatches() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (batchIds: string[]) => documentRenameApi.deleteBatches(batchIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: renameKeys.batches });
    },
  });
}

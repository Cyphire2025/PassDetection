import { useQuery, useQueryClient } from "@tanstack/react-query";
import { usePrivateMutation } from "@/hooks/use-private-mutation";
import { documentRenameApi } from "../api/document-rename.api";
import type {
  DocumentUploadProgress,
  DocumentUploadSession,
} from "../services/document-upload-batching";

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
  return usePrivateMutation({
    mutationFn: ({ title, files, onProgress, session }: {
      title: string;
      files: File[];
      onProgress?: (progress: DocumentUploadProgress) => void;
      session?: DocumentUploadSession;
    }, _context, owner) => documentRenameApi.analyze(title, files, onProgress, session, owner.requestConfig),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: renameKeys.batches });
    },
  });
}

export function useOpenRenameBatch() {
  return usePrivateMutation({
    mutationFn: (batchId: string, _context, owner) => documentRenameApi.getBatch(batchId, owner.requestConfig),
  });
}

export function useDeleteRenameBatches() {
  const queryClient = useQueryClient();
  return usePrivateMutation({
    mutationFn: (batchIds: string[], _context, owner) => documentRenameApi.deleteBatches(batchIds, owner.requestConfig),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: renameKeys.batches });
    },
  });
}

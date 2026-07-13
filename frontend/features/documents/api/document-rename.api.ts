import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  DeleteRenameBatchesResponse,
  RenameDocumentBatch,
  RenameDocumentBatchSummary,
} from "@/types/document-rename.types";

export const documentRenameApi = {
  listBatches: async (): Promise<RenameDocumentBatchSummary[]> => {
    const { data } = await apiClient.get<RenameDocumentBatchSummary[]>(API_ENDPOINTS.documentRename.batches);
    return data;
  },

  getBatch: async (batchId: string): Promise<RenameDocumentBatch> => {
    const { data } = await apiClient.get<RenameDocumentBatch>(API_ENDPOINTS.documentRename.batch(batchId));
    return data;
  },

  deleteBatches: async (batchIds: string[]): Promise<DeleteRenameBatchesResponse> => {
    const { data } = await apiClient.post<DeleteRenameBatchesResponse>(API_ENDPOINTS.documentRename.bulkDelete, {
      batch_ids: batchIds,
    });
    return data;
  },

  analyze: async (title: string, files: File[], onProgress?: (progress: number) => void): Promise<RenameDocumentBatch> => {
    const formData = new FormData();
    formData.append("title", title);
    files.forEach((file) => formData.append("files", file));
    const { data } = await apiClient.post<RenameDocumentBatch>(API_ENDPOINTS.documentRename.batches, formData, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 120_000,
      onUploadProgress: (event) => {
        if (!event.total) return;
        onProgress?.(Math.round((event.loaded / event.total) * 100));
      },
    });
    return data;
  },
};

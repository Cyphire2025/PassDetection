import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  DeleteRenameBatchesResponse,
  RenameDocumentBatch,
  RenameDocumentBatchSummary,
} from "@/types/document-rename.types";
import {
  createDocumentUploadSession,
  runChunkedDocumentUpload,
  type DocumentUploadProgress,
  type DocumentUploadSession,
} from "../services/document-upload-batching";

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

  analyze: async (
    title: string,
    files: File[],
    onProgress?: (progress: DocumentUploadProgress) => void,
    existingSession?: DocumentUploadSession,
  ): Promise<RenameDocumentBatch> => {
    const session = existingSession ?? createDocumentUploadSession(files);
    return runChunkedDocumentUpload({
      session,
      onProgress,
      uploadChunk: async (chunk, chunkIndex, reportUpload) => {
        const formData = new FormData();
        formData.append("title", title);
        formData.append("upload_id", session.uploadId);
        formData.append("chunk_id", session.chunkIds[chunkIndex]);
        formData.append("chunk_index", String(chunkIndex));
        formData.append("expected_chunk_count", String(session.chunks.length));
        formData.append("expected_file_count", String(session.totalFiles));
        chunk.forEach((file) => formData.append("files", file));
        const { data } = await apiClient.post<RenameDocumentBatch>(
          API_ENDPOINTS.documentRename.batches,
          formData,
          {
            headers: { "Content-Type": "multipart/form-data" },
            timeout: 240_000,
            onUploadProgress: (event) => reportUpload(event.loaded, event.total),
          },
        );
        return data;
      },
    });
  },
};

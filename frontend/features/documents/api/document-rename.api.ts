import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import {
  assertRequestOwner,
  capturePrivateOperationOwner,
  type OwnerBoundRequestConfig,
} from "@/lib/api/request-owner";
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

function renameOperationOwner(requestConfig?: OwnerBoundRequestConfig) {
  const initialOwner = capturePrivateOperationOwner();
  const config = {
    ...requestConfig,
    expectedOwnerUserId: requestConfig?.expectedOwnerUserId ?? initialOwner.requestConfig.expectedOwnerUserId,
    expectedAuthorityKey: requestConfig?.expectedAuthorityKey ?? initialOwner.requestConfig.expectedAuthorityKey,
  };
  const assertCurrent = () => assertRequestOwner(config);
  assertCurrent();
  return { config, assertCurrent };
}

export const documentRenameApi = {
  listBatches: async (): Promise<RenameDocumentBatchSummary[]> => {
    const { data } = await apiClient.get<RenameDocumentBatchSummary[]>(API_ENDPOINTS.documentRename.batches);
    return data;
  },

  getBatch: async (batchId: string, requestConfig?: OwnerBoundRequestConfig): Promise<RenameDocumentBatch> => {
    const owner = renameOperationOwner(requestConfig);
    const { data } = await apiClient.get<RenameDocumentBatch>(API_ENDPOINTS.documentRename.batch(batchId), owner.config);
    owner.assertCurrent();
    return data;
  },

  deleteBatches: async (batchIds: string[], requestConfig?: OwnerBoundRequestConfig): Promise<DeleteRenameBatchesResponse> => {
    const owner = renameOperationOwner(requestConfig);
    const { data } = await apiClient.post<DeleteRenameBatchesResponse>(API_ENDPOINTS.documentRename.bulkDelete, {
      batch_ids: batchIds,
    }, owner.config);
    owner.assertCurrent();
    return data;
  },

  analyze: async (
    title: string,
    files: File[],
    onProgress?: (progress: DocumentUploadProgress) => void,
    existingSession?: DocumentUploadSession,
    requestConfig?: OwnerBoundRequestConfig,
  ): Promise<RenameDocumentBatch> => {
    const owner = renameOperationOwner(requestConfig);
    const session = existingSession ?? createDocumentUploadSession(files);
    const result = await runChunkedDocumentUpload({
      session,
      onProgress: progress => { owner.assertCurrent(); onProgress?.(progress); },
      uploadChunk: async (chunk, chunkIndex, reportUpload) => {
        owner.assertCurrent();
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
            ...owner.config,
            headers: { "Content-Type": "multipart/form-data" },
            timeout: 240_000,
            onUploadProgress: (event) => {
              try { owner.assertCurrent(); } catch { return; }
              reportUpload(event.loaded, event.total);
            },
          },
        );
        owner.assertCurrent();
        return data;
      },
    });
    owner.assertCurrent();
    return result;
  },
};

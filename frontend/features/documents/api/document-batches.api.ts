import apiClient, { type ApiError } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  AbortDocumentUploadResult,
  DistributionDocumentType,
  DocumentBatchReview,
  ManualDocumentReplacement
} from "@/types/document-distribution.types";
import { runStagedDocumentUpload, type DocumentStagingManifest, type DocumentUploadProgress } from "../services/document-upload-batching";

export const documentBatchesApi = {
  uploadDocuments: async (
    groupId: string,
    documentType: DistributionDocumentType,
    manifest: DocumentStagingManifest,
    onProgress?: (progress: DocumentUploadProgress) => void,
    onManifestChange?: (manifest: DocumentStagingManifest) => void,
    signal?: AbortSignal,
  ): Promise<DocumentBatchReview> => {
    return runStagedDocumentUpload({
      manifest,
      onProgress,
      onManifestChange,
      signal,
      uploadChunk: async (chunk, chunkIndex, reportUpload) => {
        const formData = new FormData();
        formData.append("upload_id", manifest.uploadId);
        formData.append("chunk_id", chunk.chunkId);
        formData.append("chunk_index", String(chunkIndex));
        formData.append("expected_chunk_count", String(manifest.chunks.length));
        formData.append("expected_file_count", String(manifest.totalFiles));
        if (chunk.filenameReplacements?.length) {
          formData.append("filename_replacements", JSON.stringify(chunk.filenameReplacements));
        }
        chunk.receipts.forEach((receipt) =>
          formData.append("staging_receipts", receipt),
        );
        try {
          const { data } = await apiClient.post<DocumentBatchReview>(
            API_ENDPOINTS.documents.upload(groupId, documentType),
            formData,
            {
              headers: { "Content-Type": "multipart/form-data" },
              timeout: 240_000,
              signal,
              onUploadProgress: (event) => reportUpload(event.loaded, event.total),
            },
          );
          return data;
        } catch (error) {
          if ((error as Partial<ApiError> | null)?.code === "HTTP_410") {
            throw new Error(
              "The secure PDF staging receipt expired. Select and check the PDFs again; "
              + "the browser did not retain raw file copies for fallback upload.",
            );
          }
          throw error;
        }
      },
    });
  },

  abortUpload: async (
    groupId: string,
    documentType: DistributionDocumentType,
    batchId: string,
  ): Promise<AbortDocumentUploadResult> => {
    const { data } = await apiClient.post<AbortDocumentUploadResult>(
      API_ENDPOINTS.documents.abortUpload(groupId, documentType, batchId),
    );
    return data;
  },

  reuploadPassengerDocument: async (
    groupId: string,
    documentType: DistributionDocumentType,
    passengerId: string,
    file: File,
  ): Promise<DocumentBatchReview> => {
    const formData = new FormData();
    formData.append("file", file);
    const { data } = await apiClient.post<DocumentBatchReview>(
      API_ENDPOINTS.documents.reupload(groupId, documentType, passengerId),
      formData,
      {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 60_000,
      },
    );
    return data;
  },

  manualUploadPassengerDocument: async (
    groupId: string,
    documentType: DistributionDocumentType,
    passengerId: string,
    file: File,
    mode: "add" | "replace",
    replacements: ManualDocumentReplacement[]
  ): Promise<DocumentBatchReview> => {
    const body = new FormData();
    body.append("file", file);
    body.append("mode", mode);
    body.append("replacement_documents", JSON.stringify(replacements));
    return (await apiClient.post<DocumentBatchReview>(
      API_ENDPOINTS.documents.manualUpload(groupId, documentType, passengerId),
      body,
      { headers: { "Content-Type": "multipart/form-data" }, timeout: 60_000 }
    )).data;
  },

  deleteDocuments: async (
    groupId: string,
    documentType: DistributionDocumentType,
    documentIds: string[],
  ): Promise<DocumentBatchReview> => {
    const { data } = await apiClient.post<DocumentBatchReview>(
      API_ENDPOINTS.documents.deleteDocuments(groupId, documentType),
      {
        document_ids: documentIds,
      }
    );
    return data;
  },

  unassignDocuments: async (
    groupId: string,
    documentType: DistributionDocumentType,
    documentIds: string[],
  ): Promise<DocumentBatchReview> => {
    const { data } = await apiClient.post<DocumentBatchReview>(
      API_ENDPOINTS.documents.unassignDocuments(groupId, documentType),
      {
        document_ids: documentIds,
      },
    );
    return data;
  },

  saveBatch: async (batchId: string): Promise<{ batch_id: string; status: string; saved_at: string }> => {
    const { data } = await apiClient.post<{ batch_id: string; status: string; saved_at: string }>(
      API_ENDPOINTS.documents.saveBatch(batchId),
    );
    return data;
  },
};

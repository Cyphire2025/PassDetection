import { type PassportRequestConfig, capturePassportOperationOwner } from "./passport-request-config";
import { assertRequestOwner } from "@/lib/api/request-owner";
import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  PassportImportResult,
  PassportDocumentImportPreview,
  PassportDocumentImportRequest,
  PassportDocumentImportChunkRequest,
  PassportDocumentImportSaveResult,
} from "./passport-imports.types";

export const passportImportsApi = {
  importGroup: async (groupId: string, file: File, requestConfig?: PassportRequestConfig): Promise<PassportImportResult> => {
    const formData = new FormData();
    formData.append("file", file);
    const { data } = await apiClient.post<PassportImportResult>(API_ENDPOINTS.passports.groupImport(groupId), formData, { ...requestConfig,
      headers: { "Content-Type": "multipart/form-data" },
    });
    return data;
  },

  previewPassportDocuments: async (groupId: string, request: PassportDocumentImportRequest, requestConfig?: PassportRequestConfig): Promise<PassportDocumentImportPreview> => {
    const formData = new FormData();
    request.files.forEach((file) => formData.append("files", file));
    const { data } = await apiClient.post<PassportDocumentImportPreview>(API_ENDPOINTS.passports.passportDocumentPreview(groupId), formData, { ...requestConfig,
      headers: { "Content-Type": "multipart/form-data" }, timeout: 120_000,
      onUploadProgress: (event) => {
        if (requestConfig) {
          try { assertRequestOwner(requestConfig); } catch { return; }
        }
        request.onProgress?.({
          phase: event.total && event.loaded < event.total ? "uploading" : "checking",
          loaded: event.loaded,
          total: event.total ?? request.files.reduce((sum, file) => sum + file.size, 0),
        });
      },
    });
    return data;
  },

  savePassportDocuments: async (groupId: string, request: PassportDocumentImportRequest, requestConfig?: PassportRequestConfig): Promise<PassportDocumentImportSaveResult> => {
    return savePassportDocumentChunk(groupId, request, capturePassportOperationOwner(requestConfig));
  },

  savePassportDocumentsInChunks: async (groupId: string, request: PassportDocumentImportChunkRequest, requestConfig?: PassportRequestConfig): Promise<PassportDocumentImportSaveResult> => {
    const owner = capturePassportOperationOwner(requestConfig);
    const chunks = chunkFilesForUpload(request.files, request.maxChunkBytes ?? 15 * 1024 * 1024, request.maxChunkFiles ?? 50);
    const totalBytes = request.files.reduce((sum, file) => sum + file.size, 0);
    let completedBytes = 0;
    const aggregate: PassportDocumentImportSaveResult = {
      group_id: groupId,
      total_count: 0,
      accepted_count: 0,
      rejected_count: 0,
      saved_count: 0,
      accepted_documents: [],
      rejected_documents: [],
    };

    for (const chunk of chunks) {
      const chunkBytes = chunk.reduce((sum, file) => sum + file.size, 0);
      owner.assertCurrent();
      const result = await savePassportDocumentChunk(groupId, {
        files: chunk,
        onProgress: (progress) => {
          const loaded = completedBytes + Math.min(progress.loaded, chunkBytes);
          request.onProgress?.({ phase: progress.phase, loaded, total: totalBytes });
        },
      }, owner);
      owner.assertCurrent();
      completedBytes += chunkBytes;
      request.onProgress?.({ phase: "saving", loaded: completedBytes, total: totalBytes });

      aggregate.total_count += result.total_count;
      aggregate.accepted_count += result.accepted_count;
      aggregate.rejected_count += result.rejected_count;
      aggregate.saved_count += result.saved_count;
      aggregate.accepted_documents.push(...result.accepted_documents);
      aggregate.rejected_documents.push(...result.rejected_documents);
    }

    return aggregate;
  },
};

function chunkFilesForUpload(files: File[], maxBytes: number, maxFiles: number) {
  const chunks: File[][] = [];
  let current: File[] = [];
  let currentBytes = 0;

  for (const file of files) {
    const wouldExceedBytes = current.length > 0 && currentBytes + file.size > maxBytes;
    const wouldExceedCount = current.length >= maxFiles;
    if (wouldExceedBytes || wouldExceedCount) {
      chunks.push(current);
      current = [];
      currentBytes = 0;
    }
    current.push(file);
    currentBytes += file.size;
  }

  if (current.length > 0) chunks.push(current);
  return chunks;
}

async function savePassportDocumentChunk(
  groupId: string,
  request: PassportDocumentImportRequest,
  owner: ReturnType<typeof capturePassportOperationOwner>,
): Promise<PassportDocumentImportSaveResult> {
  owner.assertCurrent();
  const formData = new FormData();
  request.files.forEach((file) => formData.append("files", file));
  const { data } = await apiClient.post<PassportDocumentImportSaveResult>(API_ENDPOINTS.passports.passportDocumentSave(groupId), formData, {
    ...owner.requestConfig,
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 180_000,
    onUploadProgress: (event) => {
      try { owner.assertCurrent(); } catch { return; }
      request.onProgress?.({
        phase: event.total && event.loaded < event.total ? "uploading" : "saving",
        loaded: event.loaded,
        total: event.total ?? request.files.reduce((sum, file) => sum + file.size, 0),
      });
    },
  });
  owner.assertCurrent();
  return data;
}

import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  PassportGroupSummary,
  PassportSubmission,
  StaffApprovalRequest,
  StaffApprovalResult,
} from "@/types/passport.types";
import {
  parseStaffApprovalResponse,
  serializeStaffApprovalRequest,
} from "./staff-approval-contract";

export interface PassportImportResult {
  imported_count: number;
  updated_count: number;
  skipped_count: number;
}

export interface PassportDocumentImportItem {
  filename: string;
  staff_code?: string | null;
  document_type?: "photo" | "front" | "back" | null;
  passenger_id?: string | null;
  passenger_name?: string | null;
  accepted: boolean;
  reason?: string | null;
}

export interface PassportDocumentImportPreview {
  group_id: string;
  total_count: number;
  accepted_count: number;
  rejected_count: number;
  accepted_documents: PassportDocumentImportItem[];
  rejected_documents: PassportDocumentImportItem[];
}

export interface PassportDocumentImportProgress {
  phase: "preparing" | "uploading" | "checking" | "saving";
  loaded: number;
  total: number;
}

export interface PassportDocumentImportRequest {
  files: File[];
  onProgress?: (progress: PassportDocumentImportProgress) => void;
}

export interface PassportDocumentImportChunkRequest extends PassportDocumentImportRequest {
  maxChunkBytes?: number;
  maxChunkFiles?: number;
}

export interface BulkDeletePassportSubmissionsResult {
  deleted_count: number;
  deleted_submission_ids: string[];
  deleted_storage_objects: number;
  deleted_notifications: number;
  storage_cleanup_deferred: boolean;
}

export type PassportDocumentImportSaveResult = PassportDocumentImportPreview & { saved_count: number };
export type PassportReextractOutcome = "completed" | "failed" | "timed_out";

export interface PassportReextractResult {
  submission: PassportSubmission;
  outcome: PassportReextractOutcome;
}

interface PassportReextractOptions {
  onProgress?: (submission: PassportSubmission) => void;
  timeoutMs?: number;
}

export const passportsApi = {
  listGroups: async (): Promise<PassportGroupSummary[]> => {
    const { data } = await apiClient.get<PassportGroupSummary[]>(API_ENDPOINTS.passports.groups);
    return data;
  },

  list: async (): Promise<PassportSubmission[]> => {
    const { data } = await apiClient.get<PassportSubmission[]>(API_ENDPOINTS.passports.root);
    return data;
  },

  listByGroup: async (groupId: string, search?: string, includeDeleted = false): Promise<PassportSubmission[]> => {
    const { data } = await apiClient.get<PassportSubmission[]>(API_ENDPOINTS.passports.groupDetail(groupId), {
      params: { ...(search ? { search } : {}), ...(includeDeleted ? { include_deleted: true } : {}) },
    });
    return data;
  },

  getById: async (id: string): Promise<PassportSubmission> => {
    const { data } = await apiClient.get<PassportSubmission>(API_ENDPOINTS.passports.detail(id));
    return data;
  },

  confirm: async (id: string, confirmedFields: Record<string, string>): Promise<PassportSubmission> => {
    const { data } = await apiClient.post<PassportSubmission>(API_ENDPOINTS.passports.confirm(id), {
      confirmed_fields: confirmedFields,
    });
    return data;
  },

  staffApprove: async (
    id: string,
    request: StaffApprovalRequest,
  ): Promise<StaffApprovalResult> => {
    const response = await apiClient.post<PassportSubmission>(
      API_ENDPOINTS.passports.staffApprove(id),
      serializeStaffApprovalRequest(request),
    );
    return parseStaffApprovalResponse(
      response.data,
      response.headers as Record<string, unknown>,
    );
  },

  retryAiVerification: async (id: string): Promise<PassportSubmission> => {
    const { data } = await apiClient.post<PassportSubmission>(
      API_ENDPOINTS.passports.retryAiVerification(id),
    );
    return data;
  },

  reextract: async (
    id: string,
    options: PassportReextractOptions = {},
  ): Promise<PassportReextractResult> => {
    const { data: queued } = await apiClient.post<PassportSubmission>(API_ENDPOINTS.passports.reextract(id));
    options.onProgress?.(queued);

    let current = queued;
    const immediateOutcome = getReextractOutcome(current);
    if (immediateOutcome) return { submission: current, outcome: immediateOutcome };

    const deadline = Date.now() + (options.timeoutMs ?? 65_000);
    let delayMs = 750;
    let consecutiveFailures = 0;
    while (Date.now() < deadline) {
      await wait(delayMs);
      try {
        current = await passportsApi.getById(id);
        consecutiveFailures = 0;
        options.onProgress?.(current);
      } catch (error) {
        consecutiveFailures += 1;
        if (consecutiveFailures >= 4) throw error;
        delayMs = Math.min(2_000, delayMs + 350);
        continue;
      }

      const outcome = getReextractOutcome(current);
      if (outcome) return { submission: current, outcome };
      delayMs = Math.min(1_500, delayMs + 100);
    }
    return { submission: current, outcome: "timed_out" };
  },

  exportGroup: async (groupId: string): Promise<void> => {
    const response = await apiClient.get<Blob>(API_ENDPOINTS.passports.groupExport(groupId), {
      responseType: "blob",
    });
    downloadBlob(response.data, `passport-export-${groupId}.xlsx`);
  },

  exportGroupImages: async (groupId: string): Promise<void> => {
    const response = await apiClient.get<Blob>(API_ENDPOINTS.passports.groupImageExport(groupId), {
      responseType: "blob",
    });
    downloadBlob(response.data, getAttachmentFilename(response.headers["content-disposition"], `passport-images-${groupId}.zip`));
  },

  importGroup: async (groupId: string, file: File): Promise<PassportImportResult> => {
    const formData = new FormData();
    formData.append("file", file);
    const { data } = await apiClient.post<PassportImportResult>(API_ENDPOINTS.passports.groupImport(groupId), formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return data;
  },

  previewPassportDocuments: async (groupId: string, request: PassportDocumentImportRequest): Promise<PassportDocumentImportPreview> => {
    const formData = new FormData();
    request.files.forEach((file) => formData.append("files", file));
    const { data } = await apiClient.post<PassportDocumentImportPreview>(API_ENDPOINTS.passports.passportDocumentPreview(groupId), formData, {
      headers: { "Content-Type": "multipart/form-data" }, timeout: 120_000,
      onUploadProgress: (event) => {
        request.onProgress?.({
          phase: event.total && event.loaded < event.total ? "uploading" : "checking",
          loaded: event.loaded,
          total: event.total ?? request.files.reduce((sum, file) => sum + file.size, 0),
        });
      },
    });
    return data;
  },

  savePassportDocuments: async (groupId: string, request: PassportDocumentImportRequest): Promise<PassportDocumentImportSaveResult> => {
    const formData = new FormData();
    request.files.forEach((file) => formData.append("files", file));
    const { data } = await apiClient.post<PassportDocumentImportSaveResult>(API_ENDPOINTS.passports.passportDocumentSave(groupId), formData, {
      headers: { "Content-Type": "multipart/form-data" }, timeout: 180_000,
      onUploadProgress: (event) => {
        request.onProgress?.({
          phase: event.total && event.loaded < event.total ? "uploading" : "saving",
          loaded: event.loaded,
          total: event.total ?? request.files.reduce((sum, file) => sum + file.size, 0),
        });
      },
    });
    return data;
  },

  savePassportDocumentsInChunks: async (groupId: string, request: PassportDocumentImportChunkRequest): Promise<PassportDocumentImportSaveResult> => {
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
      const result = await passportsApi.savePassportDocuments(groupId, {
        files: chunk,
        onProgress: (progress) => {
          const loaded = completedBytes + Math.min(progress.loaded, chunkBytes);
          request.onProgress?.({ phase: progress.phase, loaded, total: totalBytes });
        },
      });
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

  exportSelectedPassports: async (submissionIds: string[]): Promise<void> => {
    const response = await apiClient.post<Blob>(
      API_ENDPOINTS.passports.selectedExport,
      { submission_ids: submissionIds },
      { responseType: "blob" },
    );
    downloadBlob(response.data, "selected-passports.xlsx");
  },

  bulkDelete: async (
    groupId: string,
    submissionIds: string[],
  ): Promise<BulkDeletePassportSubmissionsResult> => {
    const { data } = await apiClient.post<BulkDeletePassportSubmissionsResult>(
      API_ENDPOINTS.passports.bulkDelete(groupId),
      { submission_ids: submissionIds },
    );
    return data;
  },

  exportSelectedGroups: async (groupIds: string[]): Promise<void> => {
    const response = await apiClient.post<Blob>(
      API_ENDPOINTS.passports.groupsExport,
      { group_ids: groupIds },
      { responseType: "blob" },
    );
    downloadBlob(response.data, "selected-groups-passports.xlsx");
  },
};

function getReextractOutcome(submission: PassportSubmission): PassportReextractOutcome | null {
  if (
    submission.status === "failed"
    || submission.extraction_status === "extraction_failed"
    || ["failed", "dead_letter", "cancelled"].includes(submission.processing_job_status ?? "")
  ) {
    return "failed";
  }
  if (
    ["extraction_complete", "extraction_partial", "ready_for_review"].includes(submission.extraction_status)
    || submission.processing_job_status === "succeeded"
  ) {
    return "completed";
  }
  return null;
}

function wait(delayMs: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, delayMs);
  });
}

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

function downloadBlob(blob: Blob, filename: string) {
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(url);
}

function getAttachmentFilename(contentDisposition: unknown, fallback: string) {
  if (typeof contentDisposition !== "string") return fallback;
  const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  const quotedMatch = contentDisposition.match(/filename="([^"]+)"/i);
  const plainMatch = contentDisposition.match(/filename=([^;]+)/i);
  const raw = utf8Match?.[1] ?? quotedMatch?.[1] ?? plainMatch?.[1];
  if (!raw) return fallback;
  try {
    return decodeURIComponent(raw.trim()).replace(/[\\/:*?"<>|]/g, "_");
  } catch {
    return fallback;
  }
}

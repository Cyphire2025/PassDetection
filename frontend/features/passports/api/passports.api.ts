import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  PassportGroupSummary,
  PassportGroupSummaryPage,
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

export type PassportGroupSubmissionFilter =
  | "all"
  | "pending_ai"
  | "ai_approved"
  | "needs_review"
  | "staff_approved"
  | "duplicates";

export type PassportGroupSubmissionSort =
  | "name"
  | "updated_at"
  | "verification_confidence";

export interface PassportGroupSubmissionsViewParams {
  search?: string;
  include_deleted?: boolean;
  include_archived?: boolean;
  submission_filter: PassportGroupSubmissionFilter;
  sort_by: PassportGroupSubmissionSort;
  sort_order: "asc" | "desc";
  page: number;
  page_size: number;
}

export type PassportGroupSummaryStatus = "active" | "closed" | "archived";
export type PassportGroupSummaryReviewFilter =
  | "all"
  | "needs_review"
  | "has_passports"
  | "confirmed_only";

export interface PassportGroupSummariesParams {
  page: number;
  page_size: number;
  group_status?: PassportGroupSummaryStatus;
  review_filter?: PassportGroupSummaryReviewFilter;
  search?: string;
  destination?: string;
}

export interface PassportExpiryAlert {
  submission_id: string;
  client_name: string;
  client_email: string | null;
  passport_number: string | null;
  date_of_expiry: string;
  status: "expired" | "near_expiry";
}

export interface PassportGroupSubmissionsView {
  items: PassportSubmission[];
  ordered_submission_ids: string[];
  group_total: number;
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  returned_count: number;
  cluster_boundaries_preserved: boolean;
  expiry_alerts: PassportExpiryAlert[];
}

export interface BulkDeletePassportSubmissionsResult {
  deleted_count: number;
  deleted_submission_ids: string[];
  deleted_storage_objects: number;
  deleted_notifications: number;
  storage_cleanup_deferred: boolean;
}

export type PassportGroupExportKind = "passport_images" | "passport_excel";
export type PassportGroupExportMode = "all" | "incremental";

export interface PassportGroupExportHistoryItem {
  id: string;
  export_kind: PassportGroupExportKind;
  export_mode: PassportGroupExportMode;
  baseline_export_id: string | null;
  total_available_count: number;
  exported_count: number;
  pending_recipient_count: number;
  new_submission_count: number;
  compatible: boolean;
  actor_email: string | null;
  created_at: string;
  completed_at: string;
}

export interface PassportGroupExportHistory {
  group_id: string;
  export_kind: PassportGroupExportKind;
  current_submission_count: number;
  items: PassportGroupExportHistoryItem[];
  page: number;
  page_size: number;
  total_count: number;
  total_pages: number;
}

export interface PassportGroupExportHistorySubmission {
  submission_id: string;
  record_available: boolean;
  client_name: string | null;
  client_phone: string | null;
  client_email: string | null;
  passport_number: string | null;
}

export interface PassportGroupExportHistoryDetail {
  history_id: string;
  group_id: string;
  export_kind: PassportGroupExportKind;
  created_at: string;
  completed_at: string;
  exported_count: number;
  items: PassportGroupExportHistorySubmission[];
  page: number;
  page_size: number;
  total_pages: number;
}

export interface PassportGroupExportRequest {
  groupId: string;
  mode: PassportGroupExportMode;
  baselineExportId?: string;
  requestId?: string;
  supplementalFields?: string[];
  groupByField?: string;
  agencyMatchField?: string;
}

export type PassportWhatsAppTrackingStatus =
  | "all"
  | "submitted"
  | "not_submitted"
  | "multiple_submissions"
  | "needs_review"
  | "unmatched_submission"
  | "replacement"
  | "rejected_upload";

export interface PassportWhatsAppTrackingExportRequest {
  groupId: string;
  status: PassportWhatsAppTrackingStatus;
  broadcastId?: string;
}

export interface PassportGroupExportFieldOption {
  key: string;
  label: string;
  source: "whatsapp";
  selected_by_default: boolean;
}

export interface PassportGroupExportGroupingOption {
  key: string;
  label: string;
  fixed: boolean;
}

export interface PassportExcelFieldOptions {
  fields: PassportGroupExportFieldOption[];
  grouping_fields: PassportGroupExportGroupingOption[];
  default_selected_fields: string[];
  default_group_by_field: string | null;
}

export interface PassportGroupExportFieldOptions extends PassportExcelFieldOptions {
  group_id: string;
  agency_match_enabled: boolean;
  agency_match_fields: PassportGroupExportFieldOption[];
}

export interface PassportSelectedGroupsExportFieldOptions extends PassportExcelFieldOptions {
  group_ids: string[];
}

export interface PassportSelectedGroupsExportRequest {
  groupIds: string[];
  supplementalFields: string[];
  groupByField: string;
}

export interface PassportSelectedImagesExportRequest {
  groupId: string;
  submissionIds: string[];
}

export interface PassportGroupExportCompletion {
  history_id: string;
  group_id: string;
  export_kind: PassportGroupExportKind;
  status: "completed";
  completed_at: string;
}

export type PassportImageType = "visa_photo" | "passport_front" | "passport_back";

export interface PassportImageCropRect {
  x: number;
  y: number;
  width: number;
  height: number;
  rotation_degrees: number;
}

export interface PassportImageCropState {
  image_type: PassportImageType;
  original_url: string;
  editable_source_url: string;
  cropped_url: string;
  crop: PassportImageCropRect | null;
  revision: number;
  source_width: number | null;
  source_height: number | null;
  sharpness: number;
  sharpness_algorithm_version: 1 | 2;
  ai_edited: boolean;
}

export interface SavePassportImageCropRequest extends PassportImageCropRect {
  sharpness: number;
  expected_revision: number;
}

export interface VisaAiEditPreview {
  blob: Blob;
  token: string;
}

export interface ApplyVisaAiEditRequest extends SavePassportImageCropRequest {
  image: Blob;
  previewToken: string;
  prompt: string;
}

export type PassportImageLibrarySource =
  | "original"
  | "manual"
  | "ai_generated";

export interface PassportImageLibraryItem {
  id: string;
  image_type: PassportImageType;
  image_url: string;
  source: PassportImageLibrarySource;
  created_at: string;
  is_current: boolean;
  prompt?: string | null;
  model?: string | null;
}

export interface PassportImageLibrary {
  items: PassportImageLibraryItem[];
}

export interface VisaAiLibraryImage {
  id: string;
  image_url: string;
  prompt: string;
  model: string;
  created_at: string;
  is_current: boolean;
}

export interface VisaAiLibrary {
  items: VisaAiLibraryImage[];
}

export type VisaAiGenerationJobStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed";

export interface VisaAiGenerationJob {
  id: string;
  status: VisaAiGenerationJobStatus;
  prompt: string;
  attempts: number;
  max_attempts: number;
  error_message: string | null;
  result: VisaAiLibraryImage | null;
  created_at: string;
  updated_at: string;
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

  listGroupSummaries: async (
    params: PassportGroupSummariesParams,
  ): Promise<PassportGroupSummaryPage> => {
    const { data } = await apiClient.get<PassportGroupSummaryPage>(
      API_ENDPOINTS.passports.groupSummaries,
      { params },
    );
    return data;
  },

  getGroupSummary: async (
    groupId: string,
    includeArchived = false,
  ): Promise<PassportGroupSummary> => {
    const { data } = await apiClient.get<PassportGroupSummary>(
      API_ENDPOINTS.passports.groupSummary(groupId),
      {
        params: includeArchived ? { include_archived: true } : undefined,
      },
    );
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

  getImageCrop: async (
    id: string,
    imageType: PassportImageType,
  ): Promise<PassportImageCropState> => {
    const { data } = await apiClient.get<PassportImageCropState>(
      API_ENDPOINTS.passports.imageCrop(id, imageType),
    );
    return data;
  },

  getOriginalImage: async (
    id: string,
    imageType: PassportImageType,
    signal?: AbortSignal,
  ): Promise<Blob> => {
    const { data } = await apiClient.get<Blob>(
      API_ENDPOINTS.passports.originalImage(id, imageType),
      { responseType: "blob", signal },
    );
    return data;
  },

  getEditableImage: async (
    url: string,
    signal?: AbortSignal,
  ): Promise<Blob> => {
    const { data } = await apiClient.get<Blob>(url, {
      responseType: "blob",
      signal,
    });
    return data;
  },

  listImageLibrary: async (
    id: string,
    imageType: PassportImageType,
    signal?: AbortSignal,
  ): Promise<PassportImageLibraryItem[]> => {
    const { data } = await apiClient.get<PassportImageLibrary>(
      API_ENDPOINTS.passports.imageLibrary(id, imageType),
      { signal },
    );
    return data.items;
  },

  uploadImageLibraryImage: async (
    id: string,
    imageType: PassportImageType,
    image: File,
    expectedRevision: number,
  ): Promise<PassportImageLibraryItem> => {
    const formData = new FormData();
    formData.append("image", image, image.name);
    formData.append("expected_revision", String(expectedRevision));
    const { data } = await apiClient.post<PassportImageLibraryItem>(
      API_ENDPOINTS.passports.imageLibrary(id, imageType),
      formData,
      {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 120_000,
      },
    );
    return data;
  },

  useImageLibraryImage: async (
    id: string,
    imageType: PassportImageType,
    itemId: string,
    request: SavePassportImageCropRequest,
  ): Promise<PassportImageCropState> => {
    const { data } = await apiClient.post<PassportImageCropState>(
      API_ENDPOINTS.passports.imageLibraryUse(id, imageType, itemId),
      request,
      { timeout: 120_000 },
    );
    return data;
  },

  generateVisaAiPreview: async (
    id: string,
    prompt: string,
    signal?: AbortSignal,
  ): Promise<VisaAiEditPreview> => {
    const response = await apiClient.post<Blob>(
      API_ENDPOINTS.passports.visaAiPreview(id),
      { prompt },
      { responseType: "blob", timeout: 120_000, signal },
    );
    const token = response.headers["x-visa-ai-edit-token"];
    if (typeof token !== "string" || !token) {
      throw new Error("The generated Visa image did not include a save token.");
    }
    return { blob: response.data, token };
  },

  applyVisaAiEdit: async (
    id: string,
    request: ApplyVisaAiEditRequest,
  ): Promise<PassportImageCropState> => {
    const formData = new FormData();
    formData.append("image", request.image, "visa-ai-preview.jpg");
    formData.append("preview_token", request.previewToken);
    formData.append("prompt", request.prompt);
    formData.append("x", String(request.x));
    formData.append("y", String(request.y));
    formData.append("width", String(request.width));
    formData.append("height", String(request.height));
    formData.append("rotation_degrees", String(request.rotation_degrees));
    formData.append("sharpness", String(request.sharpness));
    formData.append("expected_revision", String(request.expected_revision));
    const { data } = await apiClient.post<PassportImageCropState>(
      API_ENDPOINTS.passports.visaAiApply(id),
      formData,
      {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 120_000,
      },
    );
    return data;
  },

  listVisaAiLibrary: async (id: string): Promise<VisaAiLibraryImage[]> => {
    const { data } = await apiClient.get<VisaAiLibrary>(
      API_ENDPOINTS.passports.visaAiLibrary(id),
    );
    return data.items;
  },

  generateVisaAiLibraryImage: async (
    id: string,
    prompt: string,
    signal?: AbortSignal,
  ): Promise<VisaAiLibraryImage> => {
    const { data } = await apiClient.post<VisaAiLibraryImage>(
      API_ENDPOINTS.passports.visaAiLibrary(id),
      { prompt },
      { timeout: 120_000, signal },
    );
    return data;
  },

  createVisaAiGenerationJob: async (
    id: string,
    prompt: string,
    signal?: AbortSignal,
  ): Promise<VisaAiGenerationJob> => {
    const { data } = await apiClient.post<VisaAiGenerationJob>(
      API_ENDPOINTS.passports.visaAiJobs(id),
      { prompt },
      { signal },
    );
    return data;
  },

  getActiveVisaAiGenerationJob: async (
    id: string,
    signal?: AbortSignal,
  ): Promise<VisaAiGenerationJob | null> => {
    const { data } = await apiClient.get<VisaAiGenerationJob | null>(
      API_ENDPOINTS.passports.visaAiActiveJob(id),
      { signal },
    );
    return data ?? null;
  },

  getVisaAiGenerationJob: async (
    id: string,
    jobId: string,
    signal?: AbortSignal,
  ): Promise<VisaAiGenerationJob> => {
    const { data } = await apiClient.get<VisaAiGenerationJob>(
      API_ENDPOINTS.passports.visaAiJob(id, jobId),
      { signal },
    );
    return data;
  },

  useVisaAiLibraryImage: async (
    id: string,
    generationId: string,
    request: SavePassportImageCropRequest,
  ): Promise<PassportImageCropState> => {
    const { data } = await apiClient.post<PassportImageCropState>(
      API_ENDPOINTS.passports.visaAiLibraryUse(id, generationId),
      request,
      { timeout: 120_000 },
    );
    return data;
  },

  saveImageCrop: async (
    id: string,
    imageType: PassportImageType,
    request: SavePassportImageCropRequest,
  ): Promise<PassportImageCropState> => {
    const { data } = await apiClient.put<PassportImageCropState>(
      API_ENDPOINTS.passports.imageCrop(id, imageType),
      request,
    );
    return data;
  },

  resetImageCrop: async (
    id: string,
    imageType: PassportImageType,
    expectedRevision: number,
  ): Promise<PassportImageCropState> => {
    const { data } = await apiClient.delete<PassportImageCropState>(
      API_ENDPOINTS.passports.imageCrop(id, imageType),
      {
        data: { expected_revision: expectedRevision },
      },
    );
    return data;
  },

  getGroupSubmissionsView: async (
    groupId: string,
    params: PassportGroupSubmissionsViewParams,
  ): Promise<PassportGroupSubmissionsView> => {
    const { data } = await apiClient.get<PassportGroupSubmissionsView>(
      API_ENDPOINTS.passports.groupSubmissionsView(groupId),
      { params },
    );
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

  getGroupExportHistory: async (
    groupId: string,
    kind: PassportGroupExportKind,
    page = 1,
  ): Promise<PassportGroupExportHistory> => {
    const response = await apiClient.get<PassportGroupExportHistory>(
      API_ENDPOINTS.passports.groupExportHistory(groupId),
      { params: { kind, page, page_size: 25 } },
    );
    return response.data;
  },

  getGroupExportHistoryDetail: async (
    groupId: string,
    historyId: string,
    page: number,
  ): Promise<PassportGroupExportHistoryDetail> => {
    const response = await apiClient.get<PassportGroupExportHistoryDetail>(
      API_ENDPOINTS.passports.groupExportHistoryDetail(groupId, historyId),
      { params: { page, page_size: 50 } },
    );
    return response.data;
  },

  completeGroupExportHistory: async (
    groupId: string,
    historyId: string,
  ): Promise<PassportGroupExportCompletion> => completePreparedGroupExport(
    groupId,
    historyId,
  ),

  exportGroup: async ({
    groupId,
    mode,
    baselineExportId,
    requestId,
    supplementalFields,
    groupByField,
    agencyMatchField,
  }: PassportGroupExportRequest): Promise<void> => {
    const response = await apiClient.get<Blob>(API_ENDPOINTS.passports.groupExport(groupId), {
      responseType: "blob",
      params: {
        mode,
        baseline_export_id: baselineExportId,
        request_id: requestId,
        supplemental_fields: supplementalFields === undefined
          ? undefined
          : supplementalFields.join(","),
        group_by_field: groupByField,
        agency_match_field: agencyMatchField,
      },
    });
    const historyId = requireExportHistoryId(
      response.headers["x-passport-export-history-id"],
    );
    downloadBlob(response.data, `passport-export-${groupId}.xlsx`);
    await confirmStartedGroupExport(groupId, historyId);
  },

  exportWhatsAppTracking: async ({
    groupId,
    status,
    broadcastId,
  }: PassportWhatsAppTrackingExportRequest): Promise<void> => {
    const response = await apiClient.get<Blob>(
      API_ENDPOINTS.passports.groupWhatsAppTrackingExport(groupId),
      {
        responseType: "blob",
        params: {
          status,
          broadcast_id: broadcastId,
        },
      },
    );
    downloadBlob(
      response.data,
      `whatsapp-tracking-${groupId}-${status}.xlsx`,
    );
  },

  getGroupExportFields: async (
    groupId: string,
  ): Promise<PassportGroupExportFieldOptions> => {
    const response = await apiClient.get<PassportGroupExportFieldOptions>(
      API_ENDPOINTS.passports.groupExportFields(groupId),
    );
    return response.data;
  },

  exportGroupImages: async ({
    groupId,
    mode,
    baselineExportId,
    requestId,
  }: PassportGroupExportRequest): Promise<void> => {
    const response = await apiClient.get<Blob>(API_ENDPOINTS.passports.groupImageExport(groupId), {
      responseType: "blob",
      // The backend builds a deterministic archive from private object storage
      // before sending it. Keep this one bulk download outside the ordinary
      // 30-second JSON request timeout; proxy and storage timeouts remain
      // bounded server-side.
      timeout: 0,
      params: {
        mode,
        baseline_export_id: baselineExportId,
        request_id: requestId,
      },
    });
    const historyId = requireExportHistoryId(
      response.headers["x-passport-export-history-id"],
    );
    downloadBlob(response.data, getAttachmentFilename(response.headers["content-disposition"], `passport-images-${groupId}.zip`));
    await confirmStartedGroupExport(groupId, historyId);
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

  exportSelectedGroupImages: async ({
    groupId,
    submissionIds,
  }: PassportSelectedImagesExportRequest): Promise<void> => {
    const response = await apiClient.post<Blob>(
      API_ENDPOINTS.passports.groupSelectedImageExport(groupId),
      { submission_ids: submissionIds },
      {
        responseType: "blob",
        timeout: 0,
      },
    );
    downloadBlob(
      response.data,
      getAttachmentFilename(
        response.headers["content-disposition"],
        `selected-passport-images-${groupId}.zip`,
      ),
    );
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

  getSelectedGroupsExportFields: async (
    groupIds: string[],
  ): Promise<PassportSelectedGroupsExportFieldOptions> => {
    const response = await apiClient.post<PassportSelectedGroupsExportFieldOptions>(
      API_ENDPOINTS.passports.groupsExportFields,
      { group_ids: groupIds },
    );
    return response.data;
  },

  exportSelectedGroups: async ({
    groupIds,
    supplementalFields,
    groupByField,
  }: PassportSelectedGroupsExportRequest): Promise<void> => {
    const response = await apiClient.post<Blob>(
      API_ENDPOINTS.passports.groupsExport,
      {
        group_ids: groupIds,
        supplemental_fields: supplementalFields,
        group_by_field: groupByField,
      },
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

async function completePreparedGroupExport(
  groupId: string,
  historyId: string,
): Promise<PassportGroupExportCompletion> {
  const response = await apiClient.post<PassportGroupExportCompletion>(
    API_ENDPOINTS.passports.groupExportHistoryComplete(groupId, historyId),
  );
  return response.data;
}

async function confirmStartedGroupExport(
  groupId: string,
  historyId: string,
): Promise<void> {
  try {
    await completePreparedGroupExport(groupId, historyId);
  } catch {
    throw new Error(
      "The file download started, but its history could not be confirmed. "
      + "It will not appear in download history; download again only if the file is missing.",
    );
  }
}

function requireExportHistoryId(value: unknown): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(
      "The server did not return a download confirmation ID. The file was not started.",
    );
  }
  return value.trim();
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

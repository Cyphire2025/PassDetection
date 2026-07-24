/**
 * Passport Upload API
 */

import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { PassportSubmission } from "@/types/passport.types";

const uploadSessionHeaders = (sessionId: string) => ({
  "X-Upload-Session-ID": sessionId,
});

export interface UploadReconciliationResult {
  submission_id: string | null;
}

export const uploadApi = {
  uploadPassport: async (
    token: string,
    client_name: string,
    file: File,
    passportBackFile: File,
    acquisitionMode: "camera" | "file",
    uploadIdempotencyKey: string,
    passportPhotoFile?: File | null,
    qualifierSelectionToken?: string | null,
    signal?: AbortSignal,
  ): Promise<PassportSubmission> => {
    const formData = new FormData();
    formData.append("client_name", client_name);
    formData.append("file", file);
    formData.append("acquisition_mode", acquisitionMode);
    formData.append("upload_idempotency_key", uploadIdempotencyKey);
    if (qualifierSelectionToken) {
      formData.append("qualifier_selection_token", qualifierSelectionToken);
    }
    if (passportPhotoFile) formData.append("passport_photo_file", passportPhotoFile);
    formData.append("passport_back_file", passportBackFile);

    const response = await apiClient.post(
      API_ENDPOINTS.passports.upload(token),
      formData,
      {
        headers: {
          "Content-Type": "multipart/form-data",
          ...uploadSessionHeaders(uploadIdempotencyKey),
        },
        signal,
        // Storage retries are bounded server-side; this request timeout only
        // covers durable file persistence, never OCR.
        timeout: 60_000,
      }
    );
    return response.data;
  },

  reconcileUpload: async (
    token: string,
    uploadIdempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<UploadReconciliationResult> => {
    const response = await apiClient.put<UploadReconciliationResult>(
      API_ENDPOINTS.passports.reconcileUpload(token),
      { upload_idempotency_key: uploadIdempotencyKey },
      {
        headers: uploadSessionHeaders(uploadIdempotencyKey),
        signal,
        // This is a bounded database lookup and must fail quickly enough to
        // leave a reload on the explicit recovery screen when connectivity is
        // uncertain. It never resends passport files.
        timeout: 10_000,
      },
    );
    return response.data;
  },

  getUploadStatus: async (
    token: string,
    submissionId: string,
    uploadSessionId: string,
    signal?: AbortSignal,
  ): Promise<PassportSubmission> => {
    const response = await apiClient.get<PassportSubmission>(
      API_ENDPOINTS.passports.uploadStatus(token, submissionId),
      {
        headers: uploadSessionHeaders(uploadSessionId),
        signal,
        // Status reads are intentionally short and retried by the upload flow.
        // A stalled proxy request must not consume the entire reconciliation
        // window on an unreliable mobile connection.
        timeout: 10_000,
      },
    );
    return response.data;
  },

  scanAgain: async (
    token: string,
    submissionId: string,
    uploadSessionId: string,
    signal?: AbortSignal,
  ): Promise<PassportSubmission> => {
    const response = await apiClient.post<PassportSubmission>(
      API_ENDPOINTS.passports.uploadScanAgain(token, submissionId),
      undefined,
      { headers: uploadSessionHeaders(uploadSessionId), signal },
    );
    return response.data;
  },

  getUploadDocument: async (
    token: string,
    submissionId: string,
    documentType: "front" | "back" | "photo",
    uploadSessionId: string,
    signal?: AbortSignal,
  ): Promise<Blob> => {
    const response = await apiClient.get<Blob>(
      API_ENDPOINTS.passports.uploadDocumentImage(
        token,
        submissionId,
        documentType,
      ),
      {
        headers: uploadSessionHeaders(uploadSessionId),
        responseType: "blob",
        signal,
        timeout: 15_000,
      },
    );
    return response.data;
  },

  discardUpload: async (
    token: string,
    submissionId: string,
    uploadSessionId: string,
  ): Promise<void> => {
    await apiClient.delete(API_ENDPOINTS.passports.discardUpload(token, submissionId), {
      headers: uploadSessionHeaders(uploadSessionId),
    });
  },

  submitClientReview: async (
    submissionId: string,
    uploadSessionId: string,
    data: {
      group_token: string;
      confirmed_fields: Record<string, string>;
      client_email?: string | null;
      client_phone?: string | null;
      departure_city?: string | null;
      base_city?: string | null;
      nearest_domestic_airport?: string | null;
      staff_code?: string | null;
      agent_employee_type?: "agent" | "employee" | null;
      agent_employee_code?: string | null;
      meal_preference?: string | null;
      submission_mode?: "single" | "family";
      family_group_id?: string | null;
      family_member_index?: number | null;
      family_relation?: string | null;
      family_gender?: string | null;
      family_head_name?: string | null;
      family_head_email?: string | null;
      family_head_phone?: string | null;
      custom_answers?: Array<{ question_id: string; value: string }>;
    },
  ): Promise<PassportSubmission> => {
    const response = await apiClient.post<PassportSubmission>(
      API_ENDPOINTS.passports.clientSubmit(submissionId),
      data,
      { headers: uploadSessionHeaders(uploadSessionId) },
    );
    return response.data;
  },
};

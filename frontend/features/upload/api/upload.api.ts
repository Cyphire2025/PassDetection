/**
 * Passport Upload API
 */

import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { PassportSubmission } from "@/types/passport.types";

export const uploadApi = {
  uploadPassport: async (token: string, client_name: string, file: File): Promise<PassportSubmission> => {
    const formData = new FormData();
    formData.append("client_name", client_name);
    formData.append("file", file);

    const response = await apiClient.post(
      API_ENDPOINTS.passports.upload(token),
      formData,
      {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      }
    );
    return response.data;
  },

  getUploadStatus: async (token: string, submissionId: string): Promise<PassportSubmission> => {
    const response = await apiClient.get<PassportSubmission>(
      API_ENDPOINTS.passports.uploadStatus(token, submissionId),
    );
    return response.data;
  },

  scanAgain: async (token: string, submissionId: string): Promise<PassportSubmission> => {
    const response = await apiClient.post<PassportSubmission>(
      API_ENDPOINTS.passports.uploadScanAgain(token, submissionId),
    );
    return response.data;
  },

  discardUpload: async (token: string, submissionId: string): Promise<void> => {
    await apiClient.delete(API_ENDPOINTS.passports.discardUpload(token, submissionId));
  },

  submitClientReview: async (
    submissionId: string,
    data: {
      group_token: string;
      confirmed_fields: Record<string, string>;
      client_email: string;
      client_phone: string;
    },
  ): Promise<PassportSubmission> => {
    const response = await apiClient.post<PassportSubmission>(
      API_ENDPOINTS.passports.clientSubmit(submissionId),
      data,
    );
    return response.data;
  },
};

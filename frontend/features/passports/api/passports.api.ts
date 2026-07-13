import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { PassportGroupSummary, PassportSubmission } from "@/types/passport.types";

export interface PassportImportResult {
  imported_count: number;
  skipped_count: number;
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

  reextract: async (id: string): Promise<PassportSubmission> => {
    const { data } = await apiClient.post<PassportSubmission>(API_ENDPOINTS.passports.reextract(id));
    return data;
  },

  exportGroup: async (groupId: string): Promise<void> => {
    const response = await apiClient.get<Blob>(API_ENDPOINTS.passports.groupExport(groupId), {
      responseType: "blob",
    });
    downloadBlob(response.data, `passport-export-${groupId}.xlsx`);
  },

  importGroup: async (groupId: string, file: File): Promise<PassportImportResult> => {
    const formData = new FormData();
    formData.append("file", file);
    const { data } = await apiClient.post<PassportImportResult>(API_ENDPOINTS.passports.groupImport(groupId), formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return data;
  },

  exportSelectedPassports: async (submissionIds: string[]): Promise<void> => {
    const response = await apiClient.post<Blob>(
      API_ENDPOINTS.passports.selectedExport,
      { submission_ids: submissionIds },
      { responseType: "blob" },
    );
    downloadBlob(response.data, "selected-passports.xlsx");
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

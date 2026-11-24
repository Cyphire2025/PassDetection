import type { PassportRequestConfig } from "./passport-request-config";
import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { downloadPassportExport } from "./passport-export-transfer";
import type {
  PassportSelectedGroupsExportFieldOptions,
  PassportSelectedGroupsExportRequest,
  PassportSelectedImagesExportRequest,
} from "./passport-exports.types";
import { passportImageDownloadFilename } from "./passport-export-download";

export const passportSelectionExportsApi = {
  exportSelectedPassports: async (submissionIds: string[], requestConfig?: PassportRequestConfig): Promise<void> => {
    await downloadPassportExport({
      url: API_ENDPOINTS.passports.selectedExport,
      method: "POST",
      data: { submission_ids: submissionIds },
      suggestedFilename: "selected-passports.xlsx",
    }, requestConfig);
  },

  exportSelectedGroupImages: async ({
    groupId,
    groupName,
    submissionIds,
  }: PassportSelectedImagesExportRequest, requestConfig?: PassportRequestConfig): Promise<void> => {
    await downloadPassportExport({
      url: API_ENDPOINTS.passports.groupSelectedImageExport(groupId),
      method: "POST",
      data: { submission_ids: submissionIds },
      suggestedFilename: passportImageDownloadFilename(groupName ?? groupId),
    }, requestConfig);
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
  }: PassportSelectedGroupsExportRequest, requestConfig?: PassportRequestConfig): Promise<void> => {
    await downloadPassportExport({
      url: API_ENDPOINTS.passports.groupsExport,
      method: "POST",
      data: {
        group_ids: groupIds,
        supplemental_fields: supplementalFields,
        group_by_field: groupByField,
      },
      suggestedFilename: "selected-groups-passports.xlsx",
    }, requestConfig);
  },
};


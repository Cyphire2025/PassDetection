import { downloadPassportExport } from "./passport-export-transfer";
import { type PassportRequestConfig, capturePassportOperationOwner } from "./passport-request-config";
import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { downloadStreamedResponse } from "@/lib/api/streamed-download";
import type {
  PassportGroupExportKind,
  PassportGroupExportHistory,
  PassportGroupExportHistoryDetail,
  PassportGroupExportRequest,
  PassportWhatsAppTrackingExportRequest,
  PassportGroupExportFieldOptions,
  PassportGroupExportCompletion,
} from "./passport-exports.types";
import {
  completePreparedGroupExport,
  confirmStartedGroupExport,
  requireExportHistoryId,
  passportImageDownloadFilename,
} from "./passport-export-download";

export const passportGroupExportsApi = {
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
    groupName,
    mode,
    baselineExportId,
    requestId,
    supplementalFields,
    groupByField,
    agencyMatchField,
  }: PassportGroupExportRequest, requestConfig?: PassportRequestConfig): Promise<void> => {
    const owner = capturePassportOperationOwner(requestConfig);
    const response = await downloadStreamedResponse({
      expectedOwnerUserId: owner.requestConfig.expectedOwnerUserId,
      url: API_ENDPOINTS.passports.groupExport(groupId),
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
      suggestedFilename: `${groupName?.trim() || groupId}_PASSPORTS.xlsx`,
      validateHeaders: (headers) => {
        requireExportHistoryId(headers["x-passport-export-history-id"]);
      },
    });
    owner.assertCurrent();
    const historyId = requireExportHistoryId(
      response.headers["x-passport-export-history-id"],
    );
    await confirmStartedGroupExport(groupId, historyId, owner);
  },

  exportWhatsAppTracking: async ({
    groupId,
    status,
    broadcastId,
  }: PassportWhatsAppTrackingExportRequest, requestConfig?: PassportRequestConfig): Promise<void> => {
    await downloadPassportExport({
      url: API_ENDPOINTS.passports.groupWhatsAppTrackingExport(groupId),
      params: {
        status,
        broadcast_id: broadcastId,
      },
      suggestedFilename: `whatsapp-tracking-${groupId}-${status}.xlsx`,
    }, requestConfig);
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
    groupName,
    mode,
    baselineExportId,
    requestId,
  }: PassportGroupExportRequest, requestConfig?: PassportRequestConfig): Promise<void> => {
    const owner = capturePassportOperationOwner(requestConfig);
    const response = await downloadStreamedResponse({
      expectedOwnerUserId: owner.requestConfig.expectedOwnerUserId,
      url: API_ENDPOINTS.passports.groupImageExport(groupId),
      params: {
        mode,
        baseline_export_id: baselineExportId,
        request_id: requestId,
      },
      suggestedFilename: passportImageDownloadFilename(groupName ?? groupId),
      validateHeaders: (headers) => {
        requireExportHistoryId(headers["x-passport-export-history-id"]);
      },
    });
    owner.assertCurrent();
    const historyId = requireExportHistoryId(
      response.headers["x-passport-export-history-id"],
    );
    await confirmStartedGroupExport(groupId, historyId, owner);
  },
};


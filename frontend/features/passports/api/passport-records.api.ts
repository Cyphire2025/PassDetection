import { type PassportRequestConfig, optionalRequestConfig, optionalBodylessRequestConfig, capturePassportOperationOwner } from "./passport-request-config";
import apiClient from "@/lib/api/client";
import { getReextractOutcome } from "../utils/passport-reextract";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  PassportGroupSummary,
  PassportSubmission,
  StaffApprovalRequest,
  StaffApprovalResult,
} from "@/types/passport.types";
import { parseStaffApprovalResponse, serializeStaffApprovalRequest } from "./staff-approval-contract";
import type {
  PassportGroupSubmissionsViewParams,
  PassportGroupSubmissionsView,
  BulkDeletePassportSubmissionsResult,
  BulkStaffApprovePassportSelection,
  BulkStaffApprovePassportSubmissionsResult,
  PassportReextractResult,
  PassportReextractOptions,
} from "./passport-records.types";

export const passportRecordsApi = {
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

  confirm: async (id: string, confirmedFields: Record<string, string>, requestConfig?: PassportRequestConfig): Promise<PassportSubmission> => {
    const { data } = await apiClient.post<PassportSubmission>(API_ENDPOINTS.passports.confirm(id), {
      confirmed_fields: confirmedFields,
    }, ...optionalRequestConfig(requestConfig));
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
    request: StaffApprovalRequest, requestConfig?: PassportRequestConfig
  ): Promise<StaffApprovalResult> => {
    const response = await apiClient.post<PassportSubmission>(
      API_ENDPOINTS.passports.staffApprove(id),
      serializeStaffApprovalRequest(request), ...optionalRequestConfig(requestConfig)
    );
    return parseStaffApprovalResponse(
      response.data,
      response.headers as Record<string, unknown>,
    );
  },

  retryAiVerification: async (id: string, requestConfig?: PassportRequestConfig): Promise<PassportSubmission> => {
    const { data } = await apiClient.post<PassportSubmission>(
      API_ENDPOINTS.passports.retryAiVerification(id), ...optionalBodylessRequestConfig(requestConfig)
    );
    return data;
  },

  reextract: async (
    id: string,
    options: PassportReextractOptions = {}, requestConfig?: PassportRequestConfig
  ): Promise<PassportReextractResult> => {
    const owner = capturePassportOperationOwner(requestConfig);
    const { data: queued } = await apiClient.post<PassportSubmission>(API_ENDPOINTS.passports.reextract(id), undefined, owner.requestConfig);
    owner.assertCurrent();
    options.onProgress?.(queued);

    let current = queued;
    const immediateOutcome = getReextractOutcome(current);
    if (immediateOutcome) return { submission: current, outcome: immediateOutcome };

    const deadline = Date.now() + (options.timeoutMs ?? 65_000);
    let delayMs = 750;
    let consecutiveFailures = 0;
    while (Date.now() < deadline) {
      await wait(delayMs);
      owner.assertCurrent();
      try {
        const response = await apiClient.get<PassportSubmission>(API_ENDPOINTS.passports.detail(id), owner.requestConfig);
        owner.assertCurrent();
        current = response.data;
        consecutiveFailures = 0;
        options.onProgress?.(current);
      } catch (error) {
        owner.assertCurrent();
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

  bulkDocumentFollowUp: async (
    groupId: string,
    request: { submission_ids: string[]; flagged: boolean }, requestConfig?: PassportRequestConfig
  ): Promise<{ updated_count: number; flagged: boolean }> => {
    const { data } = await apiClient.post<{ updated_count: number; flagged: boolean }>(
      API_ENDPOINTS.passports.bulkDocumentFollowUp(groupId), request, ...optionalRequestConfig(requestConfig)
    );
    return data;
  },

  bulkDelete: async (
    groupId: string,
    submissionIds: string[], requestConfig?: PassportRequestConfig
  ): Promise<BulkDeletePassportSubmissionsResult> => {
    const { data } = await apiClient.post<BulkDeletePassportSubmissionsResult>(
      API_ENDPOINTS.passports.bulkDelete(groupId),
      { submission_ids: submissionIds }, ...optionalRequestConfig(requestConfig)
    );
    return data;
  },

  bulkStaffApprove: async (
    groupId: string,
    submissions: BulkStaffApprovePassportSelection[], requestConfig?: PassportRequestConfig
  ): Promise<BulkStaffApprovePassportSubmissionsResult> => {
    const { data } = await apiClient.post<BulkStaffApprovePassportSubmissionsResult>(
      API_ENDPOINTS.passports.bulkStaffApprove(groupId),
      { submissions }, ...optionalRequestConfig(requestConfig)
    );
    return data;
  },
};

function wait(delayMs: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, delayMs);
  });
}

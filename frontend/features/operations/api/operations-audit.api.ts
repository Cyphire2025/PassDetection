import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { downloadStreamedResponse } from "@/lib/api/streamed-download";
import type {
  AnalyticsSummary,
  AuditLogPage,
  AuditLogFilters,
} from "./operations-audit.types";

export const auditOperationsApi = {
  analyticsSummary: async (days = 30): Promise<AnalyticsSummary> => {
    const { data } = await apiClient.get<AnalyticsSummary>(API_ENDPOINTS.analytics.summary, {
      params: { days },
    });
    return data;
  },

  auditLogPage: async ({
    filters,
    cursor,
    pageSize = 50,
    signal,
  }: {
    filters: AuditLogFilters;
    cursor?: string | null;
    pageSize?: number;
    signal?: AbortSignal;
  }): Promise<AuditLogPage> => {
    const { data } = await apiClient.get<AuditLogPage>(API_ENDPOINTS.auditLogs.page, {
      params: {
        ...filters,
        cursor: cursor || undefined,
        page_size: pageSize,
      },
      signal,
    });
    return data;
  },

  exportAuditLogs: async ({
    filters,
    signal,
  }: {
    filters: AuditLogFilters & { start_at: string; end_at: string };
    signal?: AbortSignal;
  }): Promise<{ truncated: boolean }> => {
    const response = await downloadStreamedResponse({
      url: API_ENDPOINTS.auditLogs.export,
      params: filters,
      suggestedFilename: `audit-logs-${new Date().toISOString().slice(0, 10)}.csv`,
      signal,
    });
    return {
      truncated: String(response.headers["x-audit-export-truncated"]).toLowerCase() === "true",
    };
  },
};

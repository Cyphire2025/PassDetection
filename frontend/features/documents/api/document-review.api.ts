import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { downloadStreamedResponse } from "@/lib/api/streamed-download";
import type { DistributionDocumentType, DocumentBatchReview, DocumentDistributionGroup } from "@/types/document-distribution.types";
import type { DocumentAssignmentExportFilter } from "./document-distribution.types";

export const documentReviewApi = {
  listGroups: async (search?: string, signal?: AbortSignal): Promise<DocumentDistributionGroup[]> => {
    const { data } = await apiClient.get<DocumentDistributionGroup[]>(
      API_ENDPOINTS.documents.groups,
      {
        params: search?.trim() ? { search: search.trim() } : undefined,
        signal,
      }
    );
    return data;
  },

  getReview: async (groupId: string, documentType: DistributionDocumentType, signal?: AbortSignal): Promise<DocumentBatchReview> => {
    const { data } = await apiClient.get<DocumentBatchReview>(API_ENDPOINTS.documents.review(groupId, documentType), { signal });
    return data;
  },

  exportReview: async (
    groupId: string,
    documentType: DistributionDocumentType,
    filter: DocumentAssignmentExportFilter,
    search: string,
    groupName?: string,
  ): Promise<void> => {
    await downloadStreamedResponse({
      url: API_ENDPOINTS.documents.reviewExport(groupId, documentType),
      params: { filter, search: search.trim() || undefined },
      suggestedFilename: documentAssignmentFilename(
        groupName ?? groupId,
        documentType,
        filter,
      ),
    });
  },
};

function documentAssignmentFilename(
  groupName: string,
  documentType: DistributionDocumentType,
  filter: DocumentAssignmentExportFilter,
) {
  const raw = `${groupName}-${documentType}-${filter}-document-assignments`.trim();
  const safe = raw.replace(/[^A-Za-z0-9_.-]+/g, "_").slice(0, 120);
  return `${safe || "document"}.xlsx`;
}

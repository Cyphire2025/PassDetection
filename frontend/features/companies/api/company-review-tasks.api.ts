import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";

export type ReviewTaskStatus = "pending" | "resolved" | "dismissed";
export interface CompanyReviewTask {
  id: string;
  group_id: string;
  traveller_id: string;
  source_submission_id: string | null;
  old_document_revision_id: string;
  new_document_revision_id: string | null;
  status: ReviewTaskStatus;
  reason_code: string;
  revision: number;
  expected_participation_revision: number;
  current_participation_revision: number;
  created_at: string;
  resolved_at: string | null;
  resolution_reason: string | null;
}
interface ReviewTaskPage { items: CompanyReviewTask[]; next_cursor: string | null; has_more: boolean }
export interface ReviewTaskResolution {
  expected_revision: number;
  expected_participation_revision: number;
  resolution: Exclude<ReviewTaskStatus, "pending">;
  reason: string;
}
const path = (companyId: string) => `${API_ENDPOINTS.companies.detail(companyId)}/review-tasks`;
export const companyReviewTasksApi = {
  async list(agencyId: string, companyId: string, status: ReviewTaskStatus | "all", cursor?: string, signal?: AbortSignal) {
    return (await apiClient.get<ReviewTaskPage>(path(companyId), { params: { agency_id: agencyId, status, cursor, page_size: 25 }, signal })).data;
  },
  async resolve(agencyId: string, companyId: string, taskId: string, body: ReviewTaskResolution) {
    return (await apiClient.patch<CompanyReviewTask>(`${path(companyId)}/${encodeURIComponent(taskId)}`, body, { params: { agency_id: agencyId } })).data;
  },
};

import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";

export const MATCH_CASE_STATUSES = ["provisional", "ambiguous", "conflicting", "unmatched", "resolved"] as const;
export type MatchCaseStatus = typeof MATCH_CASE_STATUSES[number];
export interface TravellerMatchCase {
  id: string;
  source_kind: string;
  source_row_key: string;
  status: string;
  reason_code: string;
  traveller_id: string | null;
  revision: number;
}
export interface MatchingPreview {
  items: TravellerMatchCase[];
  next_cursor: string | null;
  counts: Partial<Record<MatchCaseStatus, number>>;
  latest_job_status: string | null;
  processed_count: number;
  expected_group_revision: number;
}
export interface MatchResolution {
  traveller_id: string;
  expected_revision: number;
  expected_group_revision: number;
  reason: string;
  evidence_reviewed: true;
}
export interface MatchResolutionResult { participation_id: string; status: string }
const path = (companyId: string, groupId: string) => `${API_ENDPOINTS.companies.detail(companyId)}/groups/${encodeURIComponent(groupId)}/travellers`;
export const companyMatchingApi = {
  async preview(agencyId: string, companyId: string, groupId: string, status: MatchCaseStatus | "all", cursor?: string, signal?: AbortSignal) {
    return (await apiClient.get<MatchingPreview>(`${path(companyId, groupId)}/matching-preview`, { params: { agency_id: agencyId, status, cursor, page_size: 25 }, signal })).data;
  },
  async enqueue(agencyId: string, companyId: string, groupId: string, idempotencyKey: string) {
    return (await apiClient.post<{ job_id: string; status: string }>(`${path(companyId, groupId)}/matching-preview`, { idempotency_key: idempotencyKey }, { params: { agency_id: agencyId } })).data;
  },
  async resolve(agencyId: string, companyId: string, groupId: string, caseId: string, body: MatchResolution) {
    return (await apiClient.post<MatchResolutionResult>(`${path(companyId, groupId)}/matches/${encodeURIComponent(caseId)}/resolve`, body, { params: { agency_id: agencyId } })).data;
  },
};

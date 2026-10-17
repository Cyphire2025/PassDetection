import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";

export interface EnrollmentSource { id: string; display_name: string; status: "staff_approved" | "confirmed"; extraction_revision: number; candidate_traveller_id?: string | null; candidate_profile_revision?: number | null; candidate_change_kind?: "renewal" | "scan" | "correction" | null; candidate_display_name?: string | null }
export interface EnrollmentSourcePage { items: EnrollmentSource[]; next_cursor: string | null; expected_group_revision: number }
export interface EnrollmentInput { source_submission_id: string; expected_extraction_revision: number; expected_group_revision: number; permission_evidence_reference: string; idempotency_key: string; change_kind: "initial" | "renewal" | "scan" | "correction"; reviewed_issuing_country: string; reviewed_document_type: string; reviewed_context_confirmed: true; candidate_association_confirmed?: boolean }
export interface EnrollmentResult { traveller_id: string; passport_id: string; document_revision_id: string; copies_pending: number }
const path = (companyId: string, groupId: string) => `${API_ENDPOINTS.companies.detail(companyId)}/groups/${encodeURIComponent(groupId)}/travellers`;
export const travellerEnrollmentApi = {
  async sources(agencyId: string, companyId: string, groupId: string, search: string, cursor?: string, signal?: AbortSignal) {
    return (await apiClient.get<EnrollmentSourcePage>(`${path(companyId, groupId)}/enrollment-sources`, { params: { agency_id: agencyId, search, cursor, page_size: 25 }, signal })).data;
  },
  async enroll(agencyId: string, companyId: string, groupId: string, body: EnrollmentInput) {
    return (await apiClient.post<EnrollmentResult>(`${path(companyId, groupId)}/enroll`, body, { params: { agency_id: agencyId } })).data;
  },
};


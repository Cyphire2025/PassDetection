import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";

export type BlockedPassportStatus = "lost" | "cancelled" | "compromised";
export interface ManagedPassport { id: string; passport_hint: string; issuing_country: string; document_type: string; status: string; is_default: boolean; revision: number; issue_date: string | null; expiry_date: string | null }
export interface ManagedPassportPage { items: ManagedPassport[]; profile_revision: number; limit_reached: boolean }
const path = (companyId: string, travellerId: string) => `${API_ENDPOINTS.companies.detail(companyId)}/travellers/${encodeURIComponent(travellerId)}/passports`;
export const companyPassportsApi = {
  async list(agencyId: string, companyId: string, travellerId: string, signal?: AbortSignal) {
    return (await apiClient.get<ManagedPassportPage>(path(companyId, travellerId), { params: { agency_id: agencyId }, signal })).data;
  },
  async block(agencyId: string, companyId: string, travellerId: string, passportId: string, status: BlockedPassportStatus, profileRevision: number, passportRevision: number) {
    return (await apiClient.patch(`${path(companyId, travellerId)}/${encodeURIComponent(passportId)}`, { status, expected_profile_revision: profileRevision, expected_passport_revision: passportRevision }, { params: { agency_id: agencyId } })).data;
  },
};

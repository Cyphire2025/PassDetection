import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";

export interface ReusePolicy {
  company_id: string; enabled: boolean; revision: number;
  notice_text?: string;
  retention_mode: "until_withdrawn" | "limited"; retention_days: number | null;
  purpose_version: string | null; notice_version: string | null; processing_basis: string | null;
  configured_at: string | null;
}
export interface ReusePolicyInput {
  expected_revision: number; enabled: boolean;
}
const path = (companyId: string) => API_ENDPOINTS.companies.detail(companyId);
const params = (agencyId: string) => ({ agency_id: agencyId });

export const reuseSetupApi = {
  async policy(agencyId: string, companyId: string, signal?: AbortSignal) {
    return (await apiClient.get<ReusePolicy>(`${path(companyId)}/reuse-policy`, { params: params(agencyId), signal })).data;
  },
  async savePolicy(agencyId: string, companyId: string, body: ReusePolicyInput) {
    return (await apiClient.put<ReusePolicy>(`${path(companyId)}/reuse-policy`, body, { params: params(agencyId) })).data;
  },
};

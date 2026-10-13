import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";

export interface ReusePolicy {
  company_id: string; enabled: boolean; revision: number;
  retention_mode: "until_withdrawn" | "limited"; retention_days: number | null;
  purpose_version: string | null; notice_version: string | null; processing_basis: string | null;
  configured_at: string | null;
}
export interface ReusePolicyInput {
  expected_revision: number; enabled: boolean; retention_mode: "until_withdrawn";
  purpose_version: string | null; notice_version: string | null; processing_basis: string | null;
}
export interface GroupReuseConfig {
  group_id: string; company_id: string; group_revision: number; revision: number;
  enabled: boolean; roster_mode: "closed" | "open"; individual_identifier_type: string | null; identifier_required: boolean;
}
export type GroupReuseConfigInput = Pick<GroupReuseConfig, "enabled" | "roster_mode" | "individual_identifier_type" | "identifier_required"> & { expected_revision: number; expected_group_revision: number };
const path = (companyId: string) => API_ENDPOINTS.companies.detail(companyId);
const params = (agencyId: string) => ({ agency_id: agencyId });

export const reuseSetupApi = {
  async policy(agencyId: string, companyId: string, signal?: AbortSignal) {
    return (await apiClient.get<ReusePolicy>(`${path(companyId)}/reuse-policy`, { params: params(agencyId), signal })).data;
  },
  async savePolicy(agencyId: string, companyId: string, body: ReusePolicyInput) {
    return (await apiClient.put<ReusePolicy>(`${path(companyId)}/reuse-policy`, body, { params: params(agencyId) })).data;
  },
  async group(agencyId: string, companyId: string, groupId: string, signal?: AbortSignal) {
    return (await apiClient.get<GroupReuseConfig>(`${path(companyId)}/groups/${groupId}/reuse-config`, { params: params(agencyId), signal })).data;
  },
  async saveGroup(agencyId: string, companyId: string, groupId: string, body: GroupReuseConfigInput) {
    return (await apiClient.put<GroupReuseConfig>(`${path(companyId)}/groups/${groupId}/reuse-config`, body, { params: params(agencyId) })).data;
  },
};

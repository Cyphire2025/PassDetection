import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { Company, CompanyGroup, CompanyGroupSearch, CompanyInput, CompanyReference, CompanySearch, CompanySummary, CompanyUpdate, CursorPage } from "../types";
import type { CompanyTraveller, CompanySubmission, TravellerHistory, HistoryPage } from "../types";

const endpoints = API_ENDPOINTS.companies;
const scope = (agencyId: string) => ({ agency_id: agencyId });

export const companiesApi = {
  async workspace(signal?: AbortSignal) {
    return (await apiClient.get<{ agency_id: string }>(endpoints.workspace, { signal })).data;
  },
  async list(agencyId: string, params: CompanySearch, signal?: AbortSignal) {
    return (await apiClient.get<CursorPage<Company>>(endpoints.root, { params: { ...scope(agencyId), ...params }, signal })).data;
  },
  async lookup(agencyId: string, params: CompanySearch, signal?: AbortSignal) {
    return (await apiClient.get<CursorPage<CompanyReference>>(endpoints.lookup, { params: { ...scope(agencyId), ...params, status: "active" }, signal })).data;
  },
  async get(agencyId: string, id: string, signal?: AbortSignal) {
    return (await apiClient.get<Company>(endpoints.detail(id), { params: scope(agencyId), signal })).data;
  },
  async create(agencyId: string, body: CompanyInput) {
    return (await apiClient.post<Company>(endpoints.root, body, { params: scope(agencyId) })).data;
  },
  async update(agencyId: string, id: string, body: CompanyUpdate) {
    return (await apiClient.patch<Company>(endpoints.detail(id), body, { params: scope(agencyId) })).data;
  },
  async remove(agencyId: string, company: Company) {
    await apiClient.delete(endpoints.detail(company.id), { params: { ...scope(agencyId), expected_revision: company.revision } });
  },
  async summary(agencyId: string, id: string, signal?: AbortSignal) {
    return (await apiClient.get<CompanySummary>(endpoints.summary(id), { params: scope(agencyId), signal })).data;
  },
  async groups(agencyId: string, id: string, params: CompanyGroupSearch, signal?: AbortSignal) {
    return (await apiClient.get<CursorPage<CompanyGroup>>(endpoints.groups(id), { params: { ...scope(agencyId), ...params }, signal })).data;
  },
  async submissions(agencyId: string, id: string, params: { search: string; cursor?: string }, signal?: AbortSignal) {
    return (await apiClient.get<CursorPage<CompanySubmission>>(endpoints.submissions(id), { params: { ...scope(agencyId), ...params, page_size: 25 }, signal })).data;
  },
  async travellers(agencyId: string, id: string, params: { search: string; cursor?: string }, signal?: AbortSignal) {
    return (await apiClient.get<HistoryPage<CompanyTraveller>>(endpoints.travellers(id), { params: { ...scope(agencyId), ...params, page_size: 25 }, signal })).data;
  },
  async history(agencyId: string, id: string, travellerId: string, cursor?: string, signal?: AbortSignal) {
    return (await apiClient.get<HistoryPage<TravellerHistory>>(endpoints.travellerHistory(id, travellerId), { params: { ...scope(agencyId), cursor, page_size: 25 }, signal })).data;
  },
};

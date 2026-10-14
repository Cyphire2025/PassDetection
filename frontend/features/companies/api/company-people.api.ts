import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { CompanyDocumentPage, CompanyDocumentUpload, CompanyPeoplePage, CompanyPeopleSearch, CompanyPersonEdit, CompanyPersonRecord, CompanyOriginalDocument } from "../types/company-people";
import type { CursorPage } from "../types";

const root = (companyId: string) => `${API_ENDPOINTS.companies.detail(companyId)}/people`;
const personPath = (companyId: string, personId: string) => `${root(companyId)}/${encodeURIComponent(personId)}`;

export const companyPeopleApi = {
  async list(agencyId: string, companyId: string, params: CompanyPeopleSearch, signal?: AbortSignal) {
    return (await apiClient.get<CompanyPeoplePage>(root(companyId), { params: { agency_id: agencyId, ...params, page_size: 100 }, signal })).data;
  },
  async record(agencyId: string, companyId: string, personId: string, signal?: AbortSignal) {
    return (await apiClient.get<CompanyPersonRecord>(`${personPath(companyId, personId)}/record`, { params: { agency_id: agencyId }, signal })).data;
  },
  async update(agencyId: string, companyId: string, personId: string, body: CompanyPersonEdit) {
    return (await apiClient.patch<CompanyPersonRecord>(`${personPath(companyId, personId)}/record`, body, { params: { agency_id: agencyId } })).data;
  },
  async documents(agencyId: string, companyId: string, personId: string, cursor?: string, signal?: AbortSignal) {
    return (await apiClient.get<CompanyDocumentPage>(`${personPath(companyId, personId)}/documents`, { params: { agency_id: agencyId, cursor, page_size: 10 }, signal })).data;
  },
  async asset(agencyId: string, companyId: string, personId: string, assetId: string, signal?: AbortSignal) {
    return (await apiClient.get<Blob>(`${personPath(companyId, personId)}/assets/${encodeURIComponent(assetId)}`, { params: { agency_id: agencyId }, responseType: "blob", signal })).data;
  },
  async sources(agencyId: string, companyId: string, personId: string, cursor?: string, signal?: AbortSignal) {
    return (await apiClient.get<CursorPage<CompanyOriginalDocument>>(`${personPath(companyId, personId)}/sources`, { params: { agency_id: agencyId, cursor, page_size: 20 }, signal })).data;
  },
  async sourceAsset(agencyId: string, companyId: string, personId: string, sourceId: string, side: string, signal?: AbortSignal) {
    return (await apiClient.get<Blob>(`${personPath(companyId, personId)}/sources/${encodeURIComponent(sourceId)}/assets/${encodeURIComponent(side)}`, { params: { agency_id: agencyId }, responseType: "blob", signal })).data;
  },
  async upload(agencyId: string, companyId: string, personId: string, metadata: CompanyDocumentUpload, file: File) {
    const body = new FormData();
    body.append("metadata", JSON.stringify(metadata));
    body.append("file", file);
    return (await apiClient.post<CompanyPersonRecord>(`${personPath(companyId, personId)}/documents`, body, { params: { agency_id: agencyId }, headers: { "Content-Type": "multipart/form-data" }, timeout: 120_000 })).data;
  },
};

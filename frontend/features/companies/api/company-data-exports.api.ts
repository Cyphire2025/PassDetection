import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { CursorPage } from "../types";

export type CompanyExportKind = "excel" | "images";
export interface CompanyDataExport {
  id: string; kind: CompanyExportKind;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled" | "expired";
  processed_count: number; part_count: number;
  created_at: string; expires_at: string | null; error_code: string | null;
}
export interface CompanyExportPart {
  id: string; part_number: number; filename: string; content_type: string; byte_size: number; record_count: number;
}
type ExportPartPage = Omit<CursorPage<CompanyExportPart>, "next_cursor"> & { next_cursor: number | null };
const root = (companyId: string) => `${API_ENDPOINTS.companies.detail(companyId)}/data-exports`;
const jobPath = (companyId: string, jobId: string) => `${root(companyId)}/${encodeURIComponent(jobId)}`;
export const companyDataExportsApi = {
  async create(agencyId: string, companyId: string, kind: CompanyExportKind, idempotencyKey: string) {
    return (await apiClient.post<CompanyDataExport>(root(companyId), { kind, idempotency_key: idempotencyKey }, { params: { agency_id: agencyId } })).data;
  },
  async list(agencyId: string, companyId: string, cursor?: string, signal?: AbortSignal) {
    return (await apiClient.get<CursorPage<CompanyDataExport>>(root(companyId), { params: { agency_id: agencyId, cursor, page_size: 10 }, signal })).data;
  },
  async parts(agencyId: string, companyId: string, jobId: string, cursor?: string, signal?: AbortSignal) {
    const { data } = await apiClient.get<ExportPartPage>(`${jobPath(companyId, jobId)}/parts`, { params: { agency_id: agencyId, cursor, page_size: 25 }, signal });
    return { ...data, next_cursor: data.next_cursor === null ? null : String(data.next_cursor) };
  },
  downloadUrl(agencyId: string, companyId: string, jobId: string, partId: string) {
    return `${jobPath(companyId, jobId)}/parts/${encodeURIComponent(partId)}/download?${new URLSearchParams({ agency_id: agencyId })}`;
  },
  manifestUrl(agencyId: string, companyId: string, jobId: string) {
    return `${jobPath(companyId, jobId)}/manifest?${new URLSearchParams({ agency_id: agencyId })}`;
  },
};

import apiClient from "@/lib/api/client";
import type { GcAgencyReference } from "@/features/gc-app/types";

export interface CompanyAgencyPage { items: GcAgencyReference[]; total: number; offset: number; limit: number }

/** Use the existing bounded agency search instead of downloading its directory. */
export async function searchCompanyAgencies(search: string, offset: number, signal?: AbortSignal) {
  return (await apiClient.get<CompanyAgencyPage>("/api/v1/gc-app/admin/agencies", { params: { q: search, offset, limit: 25 }, signal })).data;
}

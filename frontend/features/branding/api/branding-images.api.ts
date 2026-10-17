import type { QueryClient } from "@tanstack/react-query";
import apiClient from "@/lib/api/client";

export type BrandingImageKind = "company-logo" | "group-banner";
export type ImageDraft = File | null | undefined;
export interface BrandingImageResult { url: string | null; revision: number | null }

export function imageVersion(url?: string | null) {
  return url ? new URL(url, "https://workspace.invalid").searchParams.get("v") ?? "" : "";
}

export async function saveBrandingImage(kind: BrandingImageKind, id: string, agencyId: string | undefined,
  draft: File | null, currentUrl?: string | null): Promise<BrandingImageResult> {
  const url = `/api/v1/branding/${kind}/${encodeURIComponent(id)}`;
  const expected_version = imageVersion(currentUrl);
  if (draft === null) return (await apiClient.delete<BrandingImageResult>(url, {
    params: { agency_id: agencyId, expected_version },
  })).data;
  const body = new FormData();
  body.append("file", draft);
  body.append("expected_version", expected_version);
  return (await apiClient.put<BrandingImageResult>(url, body, {
    params: { agency_id: agencyId }, headers: { "Content-Type": "multipart/form-data" }, timeout: 90_000,
  })).data;
}

export async function invalidateBrandingImages(client: QueryClient) {
  await Promise.all(["companies", "passports", "upload-links", "document-distribution"].map(
    (key) => client.invalidateQueries({ queryKey: [key] }),
  ));
}

import type { QueryClient } from "@tanstack/react-query";
import apiClient from "@/lib/api/client";
import { assertRequestOwner, capturePrivateOperationOwner, ownerBoundRequestConfig, type OwnerBoundRequestConfig } from "@/lib/api/request-owner";

export type BrandingImageKind = "company-logo" | "group-banner" | "group-background";
export type ImageDraft = File | null | undefined;
export interface BrandingImageResult { url: string | null; revision: number | null }

export function imageVersion(url?: string | null) {
  return url ? new URL(url, "https://workspace.invalid").searchParams.get("v") ?? "" : "";
}

export async function saveBrandingImage(kind: BrandingImageKind, id: string, agencyId: string | undefined,
  draft: File | null, currentUrl?: string | null, expectedOwnerUserId?: string,
  operationOptions?: Pick<OwnerBoundRequestConfig, "expectedAuthorityKey" | "signal">): Promise<BrandingImageResult> {
  const requestConfig = expectedOwnerUserId === undefined
    ? capturePrivateOperationOwner().requestConfig
    : { ...ownerBoundRequestConfig(expectedOwnerUserId), ...operationOptions };
  assertRequestOwner(requestConfig);
  const url = `/api/v1/branding/${kind}/${encodeURIComponent(id)}`;
  const expected_version = imageVersion(currentUrl);
  if (draft === null) {
    const response = await apiClient.delete<BrandingImageResult>(url, {
      ...requestConfig,
      params: { agency_id: agencyId, expected_version },
    });
    assertRequestOwner(requestConfig);
    return response.data;
  }
  const body = new FormData();
  body.append("file", draft);
  body.append("expected_version", expected_version);
  const response = await apiClient.put<BrandingImageResult>(url, body, {
    ...requestConfig,
    params: { agency_id: agencyId }, headers: { "Content-Type": "multipart/form-data" }, timeout: 90_000,
  });
  assertRequestOwner(requestConfig);
  return response.data;
}

export async function invalidateBrandingImages(client: QueryClient) {
  await Promise.all(["companies", "passports", "upload-links", "document-distribution"].map(
    (key) => client.invalidateQueries({ queryKey: [key] }),
  ));
}

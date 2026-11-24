import type { OwnerBoundRequestConfig } from "@/lib/api/request-owner";

/** Keep private authority outside business payloads and preserve agency scoping. */
export function companyRequestConfig(
  agencyId: string,
  owner?: OwnerBoundRequestConfig,
  params?: Record<string, unknown>,
): OwnerBoundRequestConfig {
  return { ...owner, params: { agency_id: agencyId, ...params } };
}

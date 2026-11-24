import {
  assertRequestOwner,
  capturePrivateOperationOwner,
  type OwnerBoundRequestConfig,
} from "@/lib/api/request-owner";

export type PassportRequestConfig = Pick<OwnerBoundRequestConfig, "expectedOwnerUserId" | "expectedAuthorityKey">;

/** Keep legacy callers' HTTP argument shape while accepting an initiating owner. */
export function optionalRequestConfig(config?: PassportRequestConfig): [] | [OwnerBoundRequestConfig] {
  return config ? [config] : [];
}

export function optionalBodylessRequestConfig(config?: PassportRequestConfig): [] | [undefined, OwnerBoundRequestConfig] {
  return config ? [undefined, config] : [];
}

/** Validate the mutation's initiating authority before starting a multi-step API. */
export function capturePassportOperationOwner(config?: PassportRequestConfig) {
  if (config) assertRequestOwner(config);
  return capturePrivateOperationOwner();
}

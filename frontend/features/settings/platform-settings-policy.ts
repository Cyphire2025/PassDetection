import type { ApiError } from "@/lib/api/client";

export type PlatformSettings = {
  platform_name: string;
  require_client_email: boolean;
  require_client_phone: boolean;
  duplicate_contact_policy: "block_same_group" | "allow" | "block_all";
  default_group_status: "active" | "closed";
  auto_archive_closed_groups_days: number;
  passport_data_retention_days: number;
  mrz_review_threshold: number;
  allow_manager_group_creation: boolean;
  audit_log_retention_days: number;
  updated_at: string | null;
};

export type PlatformSettingsUpdate = Omit<PlatformSettings, "updated_at"> & {
  expected_updated_at: string | null;
};

export const DEFAULT_PLATFORM_SETTINGS: PlatformSettings = {
  platform_name: "Global Connects Dashboard",
  require_client_email: false,
  require_client_phone: false,
  duplicate_contact_policy: "block_same_group",
  default_group_status: "active",
  auto_archive_closed_groups_days: 90,
  passport_data_retention_days: 365,
  mrz_review_threshold: 0.85,
  allow_manager_group_creation: true,
  audit_log_retention_days: 365,
  updated_at: null,
};

export function buildPlatformSettingsUpdate(
  settings: PlatformSettings,
  expectedUpdatedAt: string | null,
): PlatformSettingsUpdate {
  return {
    platform_name: settings.platform_name,
    require_client_email: settings.require_client_email,
    require_client_phone: settings.require_client_phone,
    duplicate_contact_policy: settings.duplicate_contact_policy,
    default_group_status: settings.default_group_status,
    auto_archive_closed_groups_days: settings.auto_archive_closed_groups_days,
    passport_data_retention_days: settings.passport_data_retention_days,
    mrz_review_threshold: settings.mrz_review_threshold,
    allow_manager_group_creation: settings.allow_manager_group_creation,
    audit_log_retention_days: settings.audit_log_retention_days,
    expected_updated_at: expectedUpdatedAt,
  };
}

export function isPlatformSettingsRevisionConflict(error: unknown): error is ApiError {
  if (!isRecord(error)) return false;
  return error.status === 409 && error.code === "PLATFORM_SETTINGS_REVISION_CONFLICT";
}

export function conflictCurrentUpdatedAt(error: unknown): string | null | undefined {
  if (!isPlatformSettingsRevisionConflict(error) || !isRecord(error.details)) return undefined;
  const value = error.details.current_updated_at;
  return typeof value === "string" || value === null ? value : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

import type { UserRole } from "@/types";

export const WHATSAPP_BROADCAST_ROLES: readonly UserRole[] = [
  "super_admin",
  "agency_admin",
  "agency_manager",
];

export const EMAIL_INTEGRATION_ROLES: readonly UserRole[] = [
  "agency_admin",
  "agency_manager",
];

export function canAccessWhatsAppBroadcasts(
  role: UserRole | null | undefined,
): boolean {
  return role !== null
    && role !== undefined
    && WHATSAPP_BROADCAST_ROLES.includes(role);
}

export function canAccessEmailIntegrations(
  role: UserRole | null | undefined,
): boolean {
  return role !== null
    && role !== undefined
    && EMAIL_INTEGRATION_ROLES.includes(role);
}

import type { User, UserRole } from "@/types";

export const WHATSAPP_BROADCAST_ROLES: readonly UserRole[] = [
  "super_admin",
  "agency_admin",
  "agency_manager",
];

export const EMAIL_INTEGRATION_ROLES: readonly UserRole[] = [
  "super_admin",
  "agency_admin",
  "agency_manager",
  "agency_staff",
];

export const GC_APP_MANAGE_CAPABILITY = "gc_app.manage";

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

/**
 * GC App access is capability-driven. The agency-admin fallback keeps existing
 * sessions usable while the backend capability field is rolled out; once a
 * capability array is present it is authoritative and fails closed.
 */
export function canManageGcApp(user: User | null | undefined): boolean {
  if (!user || !user.is_active) return false;
  if (user.role === "super_admin") return true;
  if (user.capabilities !== undefined) {
    return user.capabilities.includes(GC_APP_MANAGE_CAPABILITY);
  }
  return user.role === "agency_admin";
}

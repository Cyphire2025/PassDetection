import type { UserRole } from "@/types/auth.types";

const PASSPORT_IMAGE_EDITOR_ROLES: ReadonlySet<UserRole> = new Set([
  "super_admin",
  "agency_admin",
  "agency_manager",
  "agency_staff",
]);

export function canEditPassportImages(role: UserRole | null | undefined): boolean {
  if (role === "agency_coordinator") return false;
  return role != null && PASSPORT_IMAGE_EDITOR_ROLES.has(role);
}

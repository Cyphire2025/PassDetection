import type { User } from "@/types";

/** Only successful existing-cookie revalidation may preserve a browser epoch.
 * New login/access transitions still use setSession and always invalidate it.
 * Account timestamps also fence security changes not represented by capabilities.
 */
export function unchangedSessionAuthority(previous: User, current: User): boolean {
  const authority = (user: User) => JSON.stringify([
    user.id, user.email, user.role, user.agency_id, user.actual_role,
    user.is_active, user.credential_state, user.mfa_enabled, user.mfa_required,
    user.can_switch_access_level, user.updated_at, user.last_login_at,
    user.capabilities ? [...user.capabilities].sort() : null,
  ]);
  return authority(previous) === authority(current);
}

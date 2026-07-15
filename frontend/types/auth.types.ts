/**
 * Auth Types
 * ==========
 * Types for authentication entities — shared across features.
 */

import type { TimestampedEntity } from "./api.types";

export type UserRole = "super_admin" | "agency_admin" | "agency_manager" | "agency_staff" | "agency_coordinator";

export interface User extends TimestampedEntity {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  agency_id: string | null;
  is_active: boolean;
  last_login_at: string | null;
}

export interface AuthSession {
  user: User;
  token_type: "bearer";
  access_token_expires_at: string | null;
}

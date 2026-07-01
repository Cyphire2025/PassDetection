/**
 * Auth Types
 * ==========
 * Types for authentication entities — shared across features.
 */

import type { TimestampedEntity } from "./api.types";

export type UserRole = "super_admin" | "agency_admin" | "agency_staff";

export interface User extends TimestampedEntity {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  agency_id: string | null;
  is_active: boolean;
  last_login_at: string | null;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
}

export interface AuthSession {
  user: User;
  tokens: AuthTokens;
}

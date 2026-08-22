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
  /** Server-authoritative feature capabilities. Older sessions may omit this. */
  capabilities?: string[];
  credential_state?: "invited" | "active";
  mfa_required?: boolean;
  mfa_enabled?: boolean;
}

export interface AuthSession {
  status: "authenticated";
  user: User;
  token_type: "bearer";
  access_token_expires_at: string | null;
}

export interface AuthChallenge {
  status: "mfa_required" | "mfa_enrollment_required";
  challenge_token: string;
  expires_at: string;
  setup_secret: string | null;
  otpauth_uri: string | null;
}

export interface MFAEnrollmentSession extends AuthSession {
  recovery_codes?: string[];
}

export type AuthOutcome = AuthSession | AuthChallenge;

export interface IdentityActionCompleted {
  status: "action_completed";
  message: string;
  next_step: "return_to_mobile_app";
}

export type IdentityActionOutcome = AuthOutcome | IdentityActionCompleted;

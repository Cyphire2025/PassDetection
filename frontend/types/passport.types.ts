/**
 * Passport Types
 * ==============
 */

import type { TimestampedEntity } from "./api.types";

export type PassportStatus =
  | "pending_upload"
  | "uploaded"
  | "processing"
  | "review_required"
  | "client_submitted"
  | "confirmed"
  | "failed";

export type PassportExtractionStatus =
  | "not_started"
  | "processing"
  | "extraction_complete"
  | "extraction_partial"
  | "extraction_failed"
  | "ready_for_review";

export type UploadLinkStatus = "active" | "used" | "expired" | "revoked";

export interface ExtractedPassportFields {
  surname?: string;
  given_names?: string;
  nationality?: string;
  date_of_birth?: string;
  sex?: string;
  place_of_birth?: string;
  date_of_issue?: string;
  date_of_expiry?: string;
  passport_number?: string;
  personal_number?: string;
  issuing_country?: string;
  mrz_line_1?: string;
  mrz_line_2?: string;
  field_validation?: {
    status: "valid" | "review_required";
    issues: Array<{
      field: string;
      message: string;
      severity: "warning" | "error" | string;
    }>;
  };
  field_provenance?: Record<string, {
    source?: string;
    debug?: {
      image_relative_bbox?: [number, number, number, number];
      locator?: string;
      [key: string]: unknown;
    };
    [key: string]: unknown;
  }>;
  ai_verification?: {
    status?: string;
    model?: string;
    provider_status?: string | null;
    corrected_fields?: string[];
    filled_fields?: string[];
    duration_ms?: number;
  };
  [key: string]: unknown;  // allow validation metadata and country-specific fields
}

export interface PassportConfidenceSignal {
  name: string;
  score: number;
  weight: number;
  details?: Record<string, unknown>;
}

export interface PassportConfidenceScore {
  overall: number;
  level: "high" | "medium" | "low" | string;
  requires_manual_review: boolean;
  review_reasons: string[];
  signals: PassportConfidenceSignal[];
}

export interface PassportSubmission extends TimestampedEntity {
  id: string;
  group_id: string;
  agency_id: string;
  client_name: string;
  client_email: string | null;
  client_phone: string | null;
  departure_city: string | null;
  nearest_domestic_airport?: string | null;
  submission_mode?: "single" | "family" | string;
  family_group_id?: string | null;
  family_member_index?: number | null;
  family_relation?: string | null;
  family_gender?: string | null;
  family_head_name?: string | null;
  family_head_email?: string | null;
  family_head_phone?: string | null;
  family_broadcast_to_member?: boolean;
  image_s3_key: string;
  image_url?: string | null;
  passport_photo_s3_key?: string | null;
  passport_back_s3_key?: string | null;
  passport_photo_url?: string | null;
  passport_back_url?: string | null;
  thumbnail_s3_key: string | null;
  staff_metadata?: Record<string, string> | null;
  acquisition_mode: "camera" | "file";
  upload_idempotency_key?: string | null;
  extraction_status: PassportExtractionStatus;
  extraction_revision: number;
  status: PassportStatus;
  extracted_fields: ExtractedPassportFields | null;
  confirmed_fields: ExtractedPassportFields | null;
  overall_confidence: number | null;
  confidence_score: PassportConfidenceScore | null;
  mrz_raw: string | null;
  error_message: string | null;
  client_reviewed_at: string | null;
  confirmed_at: string | null;
  processing_job_id?: string | null;
  processing_job_status?: string | null;
  processing_progress?: number | null;
  processing_stage?: string | null;
  qr_status?: {
    status: "not_generated" | "active" | "inactive" | "expired" | "revoked" | string;
    token_version: number | null;
    created_at: string | null;
    expires_at: string | null;
    revoked_at: string | null;
  } | null;
}

export interface PassportGroupSummary {
  group_id: string;
  group_name: string;
  group_status: "active" | "closed" | "archived";
  total_passports: number;
  pending_review_count: number;
  confirmed_count: number;
  failed_count: number;
  latest_submission_at: string;
  destination: string | null;
  travel_date: string | null;
  return_date: string | null;
  package_name: string | null;
  departure_cities: string[];
  base_city_enabled: boolean;
  nearest_international_airport_enabled: boolean;
  staff_code_enabled: boolean;
  meal_preference_enabled: boolean;
  require_selfie: boolean;
  allow_files_from_device: boolean;
  ask_nearest_domestic_airport: boolean;
  notes: string | null;
}

export interface UploadLink extends TimestampedEntity {
  id: string;
  token: string;
  agency_id: string;
  client_email: string;
  client_name: string;
  status: UploadLinkStatus;
  expires_at: string;
  created_by_user_id: string;
  used_at: string | null;
  revoked_at: string | null;
}

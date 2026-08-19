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
  | "failed"
  | "pending_extraction"
  | "extracting"
  | "ready_for_client_review"
  | "submitted"
  | "ai_approved"
  | "needs_review"
  | "staff_approved";

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
  place_of_issue?: string;
  /** @deprecated Read-only compatibility for records created before place_of_issue. */
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
    available?: boolean;
    model?: string;
    provider_status?: string | null;
    corrected_fields?: string[];
    filled_fields?: string[];
    absent_fields?: string[];
    duration_ms?: number;
    attempts?: number;
    document_class?: string;
    page_type?: string;
    image_quality?: string;
    classification_confidence?: number;
    reason_code?: string;
  };
  manual_review_conflicts?: PassportExtractionConflict[];
  [key: string]: unknown;  // allow validation metadata and country-specific fields
}

export interface PassportExtractionConflict {
  field: string;
  manual_value: string;
  extracted_value: string | null;
  status: "mismatch" | "not_extracted";
}

export type PassportVerificationFieldName =
  | "surname"
  | "given_names"
  | "passport_number"
  | "nationality"
  | "place_of_issue"
  /** @deprecated Persisted legacy verification results may still contain this field. */
  | "issuing_country"
  | "date_of_birth"
  | "date_of_issue"
  | "date_of_expiry"
  | "sex";

export type PassportVerificationVerdict = "correct" | "suspicious" | "incorrect";

export interface PassportVerificationField {
  field: PassportVerificationFieldName;
  verdict: PassportVerificationVerdict;
  observed_value: string | null;
  confidence: number;
  reason_code: string;
}

export interface PassportPostSubmissionVerification {
  verification_status: "ai_approved" | "needs_review";
  confidence: number;
  incorrect_fields: PassportVerificationFieldName[];
  suspicious_fields: PassportVerificationFieldName[];
  explanation: string;
  provider_status: string;
  reason_code: string | null;
  model: string | null;
  fields: PassportVerificationField[];
  stale_after_staff_edit: boolean;
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
  custom_answers?: Array<{
    question_id: string;
    label: string;
    value: string;
  }>;
  custom_detail_answers?: Array<{
    detail_id: string;
    label: string;
    value: string;
  }>;
  acquisition_mode: "camera" | "file";
  qualifier_enabled_snapshot?: boolean;
  qualifier_is_self?: boolean | null;
  qualifier_relation_code?: string | null;
  qualifier_relation_label?: string | null;
  qualifier_selected_at?: string | null;
  extraction_status: PassportExtractionStatus;
  extraction_revision: number;
  status: PassportStatus;
  extracted_fields: ExtractedPassportFields | null;
  confirmed_fields: ExtractedPassportFields | null;
  extraction_conflicts?: PassportExtractionConflict[];
  post_submission_verification?: PassportPostSubmissionVerification | null;
  post_submission_verification_revision?: number;
  post_submission_verified_at?: string | null;
  verification_reviewed_by_user_id?: string | null;
  verification_reviewer_name?: string | null;
  verification_reviewed_at?: string | null;
  duplicate_cluster_id?: string | null;
  duplicate_cluster_size?: number;
  duplicate_cluster_member_ids?: string[];
  duplicate_match_basis?: string | null;
  verification_confidence?: number | null;
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

export type StaffApprovalOutcome = "approved" | "already_approved";

export interface StaffApprovalRequest {
  confirmedFields?: Record<string, string>;
  expectedExtractionRevision: number;
  reviewReason?: string;
}

export interface StaffApprovalResult {
  submission: PassportSubmission;
  outcome: StaffApprovalOutcome;
  extractionRevision: number;
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
  timezone: string;
  package_name: string | null;
  departure_cities: string[];
  base_city_enabled: boolean;
  nearest_international_airport_enabled: boolean;
  staff_code_enabled: boolean;
  agent_employee_code_enabled: boolean;
  meal_preference_enabled: boolean;
  require_selfie: boolean;
  allow_files_from_device: boolean;
  ask_nearest_domestic_airport: boolean;
  relation_with_qualifier_enabled: boolean;
  designation_enabled: boolean;
  agency_dealership_name_enabled: boolean;
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

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
  image_s3_key: string;
  image_url?: string | null;
  thumbnail_s3_key: string | null;
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

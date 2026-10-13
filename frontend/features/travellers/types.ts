import type { CustomUploadDetail, CustomUploadQuestion } from "@/features/passports/api/upload-links.api";

export type ReturningMethod = "phone" | "passport" | "code";
export type DocumentQuestion = "date_of_birth" | "issue_date" | "expiry_date";
export interface ReturningCapabilities { enabled: boolean; code_label: string | null }
export interface ClaimTransition {
  stage: "contact" | "identify" | "passport" | "challenge" | "confirm" | "recovery" | "review";
  questions?: DocumentQuestion[];
  available_questions?: DocumentQuestion[];
  can_change_question?: boolean;
  expires_in_seconds?: number;
}
export interface ClaimStart {
  group_token: string;
  method: ReturningMethod;
  phone_number?: string;
  passport_number?: string;
  issuing_country?: string;
  document_type: "P";
  individual_code?: string;
}
export interface PassportProof { passport_number?: string; issuing_country?: string; document_type?: string; individual_code?: string }
export interface MaskedCandidates { items: Array<{ handle: string; label: string; passport_hint: string }>; narrowing_required: boolean }
export interface ReturningDocument { id: string; label: string; content_type: string; available: boolean }
export interface CurrentDetailField { key: string; label: string; required: boolean; options: string[]; type: "text" | "select" | "email" }
export interface AvailablePassport { id: string; number: string; issuing_country: string; document_type: string; is_default: boolean; expiry_date: string | null }
export interface ReturningHistory {
  display_name: string;
  contact_phone: string | null;
  extracted_fields?: Record<string, string | null>;
  passport: { id: string; number: string; issuing_country: string; document_type: string; date_of_birth: string | null; issue_date: string | null; expiry_date: string | null; revision: number } | null;
  available_passports?: AvailablePassport[];
  documents: ReturningDocument[];
  suitability: { outcome: "suitable" | "replacement_required" | "review_required" | "cannot_assess"; reason_codes: string[] };
  group_requirements: { custom_questions: CustomUploadQuestion[]; custom_details: CustomUploadDetail[]; require_selfie: boolean; require_contact_phone: boolean; current_detail_fields?: CurrentDetailField[] };
  missing_requirements?: string[];
  question_version: string;
  review_version: string;
  saved_answers?: { custom_answers: Record<string, string>; custom_detail_answers: Record<string, string>; current_details: Record<string, string> };
  participation_revision: number | null;
}
export interface ReturningCompletion {
  owned_source?: { source_submission_id: string; expected_extraction_revision: number };
  question_version: string;
  review_version: string;
  expected_participation_revision?: number;
  custom_answers: Record<string, string>;
  custom_detail_answers: Record<string, string>;
  current_details?: Record<string, string>;
  information_confirmed: true;
  idempotency_key: string;
}
export interface CompletionResult { status: "submitted" | "accepted"; participation_id: string; source_submission_id?: string }
export interface ReturningOwnedSource { source_submission_id: string; expected_extraction_revision: number; uploadSessionId: string }
export interface ReplacementRequest { reviewVersion: string; displayName: string; changeKind: "renewal" | "scan" | "correction" }
export interface ReplacementIntent extends ReplacementRequest { uploadSessionId: string; idempotencyKey: string }
export interface ReplacementCandidateInput { source_submission_id: string; expected_extraction_revision: number; review_version: string; change_kind: ReplacementRequest["changeKind"]; idempotency_key: string }
export interface ReplacementCandidateResult { status: "candidate_pending_review"; match_case_id: string }

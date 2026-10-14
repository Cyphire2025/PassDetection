import type { FreshCollection } from "@/features/upload/api/fresh-draft.types";

export type DraftSide = "front" | "back" | "cover" | "back_cover" | "photo";
export interface DraftPayload {
  passport_fields: Record<string, string>;
  current_details: Record<string, string>;
  custom_answers: Record<string, string>;
  custom_detail_answers: Record<string, string>;
}
export interface ReturningDraft extends DraftPayload {
  collection?: FreshCollection | null;
  id: string; revision: number; expires_at: string; status: "active" | "submitted";
  verified_phone: string | null;
  documents: Array<{ id: string; side: DraftSide; state: "uploading" | "ready" }>;
  extraction_status: "none" | "pending" | "running" | "succeeded" | "failed";
  extracted_fields: Record<string, string>;
  ecr_status?: "none" | "pending" | "running" | "succeeded" | "failed"; ecr_result?: "ECR" | "NA" | "REVIEW" | null;
  source_submission_id?: string | null; participation_id?: string | null; result_status?: "accepted" | "submitted" | null;
}
export interface DraftSubmission {
  expected_revision: number; review_version: string; question_version: string;
  expected_participation_revision?: number; information_confirmed: true; idempotency_key: string;
  owned_source?: { source_submission_id: string; expected_extraction_revision: number };
}

import type { DraftPayload, ReturningDraft } from "@/features/travellers/api/draft.types";

export interface FreshCollection {
  acquisition_mode: "file" | "camera"; visa_photo_source?: "file" | "camera" | null;
  qualifier_selection_token?: string | null; submission_mode: "single" | "family";
  family_group_id?: string; family_member_index?: number; family_relation?: string; family_gender?: string;
  family_head_name?: string; family_head_email?: string; family_head_phone?: string;
}
export interface FreshPayload extends DraftPayload { collection: FreshCollection | null }
export interface FreshDraft extends Omit<ReturningDraft, "result_status"> { collection: FreshCollection | null; phone_verification_id?: string | null; phone_verification_expires_at?: string | null; source_submission_id?: string | null; result_status?: "submitted" | "needs_review" | "ai_approved" | "staff_approved" | null }
export interface FreshContactChallenge { challenge_id: string; expires_in_seconds: number; resend_after_seconds: number }
export interface FreshContactProof { phone_verification_id: string; phone_number: string; expires_in_seconds: number }

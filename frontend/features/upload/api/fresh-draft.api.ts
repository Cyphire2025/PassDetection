import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { DraftPayload, DraftSide, ReturningDraft } from "@/features/travellers/api/returning-draft.api";
import type { QualifierSelectionRequest } from "../services/relation-qualifier";

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
export function freshDraftApi(token: string, sessionId: string) {
  const path = `/api/v1/public-drafts/${encodeURIComponent(token)}`;
  const options = (signal?: AbortSignal) => ({ signal, headers: { "X-Upload-Session-ID": sessionId } });
  return {
    start: async (signal?: AbortSignal) => (await apiClient.post<FreshDraft>(path, undefined, options(signal))).data,
    read: async (signal?: AbortSignal) => (await apiClient.get<FreshDraft>(path, options(signal))).data,
    save: async (payload: FreshPayload, revision: number, key: string, signal?: AbortSignal) => (await apiClient.put<FreshDraft>(path, { ...payload, expected_revision: revision, idempotency_key: key }, options(signal))).data,
    upload: async (side: DraftSide, file: File, revision: number, key: string, signal?: AbortSignal) => {
      const body = new FormData(); body.set("file", file); body.set("expected_revision", String(revision)); body.set("idempotency_key", key);
      return (await apiClient.post<FreshDraft>(`${path}/documents/${side}`, body, { ...options(signal), headers: { ...options(signal).headers, "Content-Type": "multipart/form-data" } })).data;
    },
    document: async (id: string, signal?: AbortSignal) => (await apiClient.get<Blob>(`${path}/documents/${encodeURIComponent(id)}`, { ...options(signal), responseType: "blob" })).data,
    requestCode: async (email: string, phone_number: string, signal?: AbortSignal) => (await apiClient.post<FreshContactChallenge>(`${path}/contact/request`, { group_token: token, email, phone_number }, options(signal))).data,
    verifyCode: async (challenge_id: string, code: string, signal?: AbortSignal) => (await apiClient.post<FreshContactProof>(`${path}/contact/verify`, { group_token: token, challenge_id, code }, options(signal))).data,
    qualifier: async (choice: QualifierSelectionRequest, signal?: AbortSignal) => (await apiClient.post<{ selection_token: string }>(API_ENDPOINTS.uploadLinks.qualifierSelection(token), choice, options(signal))).data,
    complete: async (revision: number, phone_verification_id: string, idempotency_key: string, signal?: AbortSignal) => (await apiClient.post<{ source_submission_id: string; status: string }>(`${path}/complete`, { expected_revision: revision, phone_verification_id, idempotency_key, information_confirmed: true }, options(signal))).data,
  };
}

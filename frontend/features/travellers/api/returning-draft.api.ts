import apiClient from "@/lib/api/client";
import type { CompletionResult } from "../types";
import type { FreshCollection } from "@/features/upload/api/fresh-draft.api";

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
  source_submission_id?: string | null;
  participation_id?: string | null;
  result_status?: "accepted" | "submitted" | null;
}
export interface DraftSubmission {
  expected_revision: number; review_version: string; question_version: string;
  expected_participation_revision?: number; information_confirmed: true; idempotency_key: string;
  owned_source?: { source_submission_id: string; expected_extraction_revision: number };
}
const path = "/api/v1/returning/draft";
const bound = (draftId: string) => ({ "X-Returning-Draft-ID": draftId });
export const returningDraftApi = {
  start: async (review_version: string, signal?: AbortSignal) => (await apiClient.post<ReturningDraft>(path, { review_version }, { signal })).data,
  read: async (draftId: string, signal?: AbortSignal) => (await apiClient.get<ReturningDraft>(path, { signal, headers: bound(draftId) })).data,
  save: async (payload: DraftPayload & { collection?: FreshCollection | null }, expected_revision: number, idempotency_key: string, draftId: string, signal?: AbortSignal) => (await apiClient.put<ReturningDraft>(path, { ...payload, expected_revision, idempotency_key }, { signal, headers: bound(draftId) })).data,
  upload: async (side: DraftSide, file: File, revision: number, idempotencyKey: string, draftId: string, signal?: AbortSignal) => {
    const body = new FormData(); body.set("file", file); body.set("expected_revision", String(revision)); body.set("idempotency_key", idempotencyKey);
    return (await apiClient.post<ReturningDraft>(`${path}/documents/${side}`, body, { signal, headers: { ...bound(draftId), "Content-Type": "multipart/form-data" } })).data;
  },
  document: async (id: string, draftId: string, signal?: AbortSignal) => (await apiClient.get<Blob>(`${path}/documents/${encodeURIComponent(id)}`, { signal, responseType: "blob", headers: bound(draftId) })).data,
  complete: async (body: DraftSubmission, draftId: string, signal?: AbortSignal, uploadSessionId?: string) => (await apiClient.post<CompletionResult>(`${path}/complete`, body, { signal, headers: { ...bound(draftId), ...(uploadSessionId ? { "X-Upload-Session-ID": uploadSessionId } : {}) } })).data,
};

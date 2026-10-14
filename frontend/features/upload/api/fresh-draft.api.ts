import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { DraftSide } from "@/features/travellers/api/draft.types";
import { draftUploadBody } from "@/features/travellers/api/draft-upload-body";
import { draftImageLifecycleApi } from "@/features/travellers/api/draft-image-lifecycle.api";
import type { QualifierSelectionRequest } from "../services/relation-qualifier";
import type { FreshDraft, FreshPayload, FreshContactChallenge, FreshContactProof } from "./fresh-draft.types";
export type { FreshCollection, FreshDraft, FreshPayload, FreshContactChallenge, FreshContactProof } from "./fresh-draft.types";
export function freshDraftApi(token: string, sessionId: string) {
  const path = `/api/v1/public-drafts/${encodeURIComponent(token)}`;
  const options = (signal?: AbortSignal) => ({ signal, headers: { "X-Upload-Session-ID": sessionId } });
  return {
    ...draftImageLifecycleApi<FreshDraft>(path, options().headers),
    start: async (signal?: AbortSignal) => (await apiClient.post<FreshDraft>(path, undefined, options(signal))).data,
    read: async (signal?: AbortSignal) => (await apiClient.get<FreshDraft>(path, options(signal))).data,
    save: async (payload: FreshPayload, revision: number, key: string, signal?: AbortSignal) => (await apiClient.put<FreshDraft>(path, { ...payload, expected_revision: revision, idempotency_key: key }, options(signal))).data,
    upload: async (side: DraftSide, file: File, revision: number, key: string, signal?: AbortSignal, expectedAssetId: string | null = null) => {
      const body = draftUploadBody(file, revision, key, expectedAssetId);
      return (await apiClient.post<FreshDraft>(`${path}/documents/${side}`, body, { ...options(signal), headers: { ...options(signal).headers, "Content-Type": "multipart/form-data" } })).data;
    },
    document: async (id: string, signal?: AbortSignal) => (await apiClient.get<Blob>(`${path}/documents/${encodeURIComponent(id)}`, { ...options(signal), responseType: "blob" })).data,
    requestCode: async (email: string, phone_number: string, signal?: AbortSignal) => (await apiClient.post<FreshContactChallenge>(`${path}/contact/request`, { group_token: token, email, phone_number }, options(signal))).data,
    verifyCode: async (challenge_id: string, code: string, signal?: AbortSignal) => (await apiClient.post<FreshContactProof>(`${path}/contact/verify`, { group_token: token, challenge_id, code }, options(signal))).data,
    qualifier: async (choice: QualifierSelectionRequest, signal?: AbortSignal) => (await apiClient.post<{ selection_token: string }>(API_ENDPOINTS.uploadLinks.qualifierSelection(token), choice, options(signal))).data,
    complete: async (revision: number, phone_verification_id: string, idempotency_key: string, signal?: AbortSignal) => (await apiClient.post<{ source_submission_id: string; status: string }>(`${path}/complete`, { expected_revision: revision, phone_verification_id, idempotency_key, information_confirmed: true }, options(signal))).data,
  };
}

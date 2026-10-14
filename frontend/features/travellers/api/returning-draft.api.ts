import apiClient from "@/lib/api/client";
import type { CompletionResult } from "../types";
import type { FreshCollection } from "@/features/upload/api/fresh-draft.types";
import type { DraftPayload, DraftSide, DraftSubmission, ReturningDraft } from "./draft.types";
import { draftUploadBody } from "./draft-upload-body";
import { draftImageLifecycleApi } from "./draft-image-lifecycle.api";
export type { DraftPayload, DraftSide, DraftSubmission, ReturningDraft } from "./draft.types";
const path = "/api/v1/returning/draft";
const bound = (draftId: string) => ({ "X-Returning-Draft-ID": draftId });
export const returningDraftApi = {
  activity: (draftId: string, signal?: AbortSignal) => draftImageLifecycleApi<ReturningDraft>(path, bound(draftId)).activity(signal),
  discard: (revision: number, draftId: string, signal?: AbortSignal, keepalive = false) => draftImageLifecycleApi<ReturningDraft>(path, bound(draftId)).discard(revision, signal, keepalive),
  start: async (review_version: string, signal?: AbortSignal) => (await apiClient.post<ReturningDraft>(path, { review_version }, { signal })).data,
  read: async (draftId: string, signal?: AbortSignal) => (await apiClient.get<ReturningDraft>(path, { signal, headers: bound(draftId) })).data,
  save: async (payload: DraftPayload & { collection?: FreshCollection | null }, expected_revision: number, idempotency_key: string, draftId: string, signal?: AbortSignal) => (await apiClient.put<ReturningDraft>(path, { ...payload, expected_revision, idempotency_key }, { signal, headers: bound(draftId) })).data,
  upload: async (side: DraftSide, file: File, revision: number, idempotencyKey: string, draftId: string, signal?: AbortSignal, expectedAssetId: string | null = null) => {
    const body = draftUploadBody(file, revision, idempotencyKey, expectedAssetId);
    return (await apiClient.post<ReturningDraft>(`${path}/documents/${side}`, body, { signal, headers: { ...bound(draftId), "Content-Type": "multipart/form-data" } })).data;
  },
  document: async (id: string, draftId: string, signal?: AbortSignal) => (await apiClient.get<Blob>(`${path}/documents/${encodeURIComponent(id)}`, { signal, responseType: "blob", headers: bound(draftId) })).data,
  complete: async (body: DraftSubmission, draftId: string, signal?: AbortSignal, uploadSessionId?: string) => (await apiClient.post<CompletionResult>(`${path}/complete`, body, { signal, headers: { ...bound(draftId), ...(uploadSessionId ? { "X-Upload-Session-ID": uploadSessionId } : {}) } })).data,
};

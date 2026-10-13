import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { ClaimStart, ClaimTransition, CompletionResult, DocumentQuestion, MaskedCandidates, PassportProof, ReturningCapabilities, ReturningCompletion, ReturningHistory } from "../types";
import type { ReplacementCandidateInput, ReplacementCandidateResult } from "../types";

const endpoints = API_ENDPOINTS.returning;
/** Claim/grant secrets remain in httpOnly cookies; none are exposed to this API. */
const post = async <T>(url: string, body: unknown, signal?: AbortSignal): Promise<T> => (await apiClient.post<T>(url, body, { signal })).data;

export const returningApi = {
  capabilities: async (groupToken: string, signal?: AbortSignal) => (await apiClient.get<ReturningCapabilities>(endpoints.capabilities, { params: { group_token: groupToken }, signal })).data,
  start: (body: ClaimStart, signal?: AbortSignal) => post<ClaimTransition>(endpoints.claims, body, signal),
  requestOtp: (signal?: AbortSignal) => post<{ expires_in_seconds: number; resend_after_seconds: number }>(endpoints.otpRequest, {}, signal),
  verifyOtp: (code: string, signal?: AbortSignal) => post<ClaimTransition>(endpoints.otpVerify, { code }, signal),
  candidates: async (signal?: AbortSignal) => (await apiClient.get<MaskedCandidates>(endpoints.candidates, { signal })).data,
  selectCandidate: (handle: string, signal?: AbortSignal) => post<ClaimTransition>(endpoints.candidate, { handle }, signal),
  passport: (body: PassportProof, signal?: AbortSignal) => post<ClaimTransition>(endpoints.passport, body, signal),
  challenge: (answers: Partial<Record<DocumentQuestion, string>>, signal?: AbortSignal) => post<ClaimTransition>(endpoints.challenge, { answers }, signal),
  changeQuestion: (field: DocumentQuestion, signal?: AbortSignal) => post<ClaimTransition>(endpoints.changeChallenge, { field }, signal),
  confirm: (contactChange: boolean, actingFor: "self" | "family", signal?: AbortSignal) => post<ClaimTransition>(endpoints.confirm, { contact_change_confirmed: contactChange, acting_for: actingFor }, signal),
  history: async (signal?: AbortSignal) => (await apiClient.get<ReturningHistory>(endpoints.history, { signal })).data,
  selectPassport: (passportId: string, signal?: AbortSignal) => post<ReturningHistory>("/api/v1/returning/passport-selection", { passport_id: passportId }, signal),
  complete: async (body: ReturningCompletion, signal?: AbortSignal, uploadSessionId?: string) => (await apiClient.post<CompletionResult>(endpoints.complete, body, { signal, ...(uploadSessionId ? { headers: { "X-Upload-Session-ID": uploadSessionId } } : {}) })).data,
  replacement: async (body: ReplacementCandidateInput, uploadSessionId: string, signal?: AbortSignal) => (await apiClient.post<ReplacementCandidateResult>("/api/v1/returning/replacement-candidate", body, { headers: { "X-Upload-Session-ID": uploadSessionId }, signal })).data,
  detectedHistory: async (body: { group_token: string; source_submission_id: string; expected_extraction_revision: number }, uploadSessionId: string, signal?: AbortSignal) => (await apiClient.post<{ available: boolean }>("/api/v1/returning/detected-history", body, { headers: { "X-Upload-Session-ID": uploadSessionId }, signal })).data,
  requestContact: (phoneNumber: string, signal?: AbortSignal) => post<{ expires_in_seconds: number; resend_after_seconds: number }>(endpoints.contactRequest, { phone_number: phoneNumber }, signal),
  verifyContact: (code: string, signal?: AbortSignal) => post<ClaimTransition>(endpoints.contactVerify, { code }, signal),
  document: async (id: string, signal?: AbortSignal) => (await apiClient.get<Blob>(endpoints.document(id), { signal, responseType: "blob" })).data,
};

"use client";

import { useEffect, useState } from "react";
import { normalizePhoneNumber } from "@/lib/utils/phone-number";
import type { FreshDraftState } from "./use-fresh-draft";
import { useFreshContactChallenge } from "./use-fresh-contact-challenge";

export interface FreshProof { id: string; email: string; phone: string; expiresAt: number }

/** Contact proof is usable only after its authoritative draft revision is read. */
export function useFreshContact(state: FreshDraftState, onProof: (proof: FreshProof | null) => void, rejectedProof?: FreshProof | null) {
  const email = state.payload!.current_details.client_email ?? "", phone = state.payload!.current_details.client_phone ?? "";
  const [proof, setProof] = useState<FreshProof | null>(() => state.draft?.phone_verification_id && state.draft.phone_verification_expires_at ? { id: state.draft.phone_verification_id, email, phone: normalizePhoneNumber(phone) ?? phone, expiresAt: Date.parse(state.draft.phone_verification_expires_at) } : null);
  const normalized = normalizePhoneNumber(phone);
  const { challenge, setChallenge, code, setCode, now, request, resend } = useFreshContactChallenge(state, email, normalized);
  const valid = proof && proof !== rejectedProof && proof.email === email.trim() && proof.phone === normalized && proof.expiresAt > now;
  useEffect(() => { onProof(valid ? proof : null); }, [valid, proof, onProof]);
  const verify = () => {
    if (!challenge) return;
    void state.serialized(async (signal) => {
      const result = await state.api.verifyCode(challenge.id, code, signal);
      return { result, signal, receivedAt: Date.now() };
    }, true).then(async ({ result, signal, receivedAt }) => {
      // Verification advances the server revision. Read it before submission
      // can use the proof, without nesting another serialized operation.
      await state.refresh();
      signal.throwIfAborted();
      const next = { id: result.phone_verification_id, email: challenge.email, phone: result.phone_number, expiresAt: receivedAt + result.expires_in_seconds * 1000 };
      setProof(next); setChallenge(undefined); setCode("");
    }).catch(() => undefined);
  };
  const currentChallenge = challenge && challenge.email === email.trim() && challenge.phone === normalized;
  const challengeExpired = Boolean(challenge && challenge.expiresAt <= now);
  return { email, phone, normalized, valid, request, verify, currentChallenge, resend, challengeExpired, code, setCode };
}

"use client";

import { useEffect, useState } from "react";
import { normalizePhoneNumber } from "@/lib/utils/phone-number";
import { validContactEmail } from "../components/upload-contact-verification";
import type { FreshDraftState } from "./use-fresh-draft";

export interface FreshProof { id: string; email: string; phone: string; expiresAt: number }

/** Contact mutations advance the shared draft revision before their UI result is exposed. */
export function useFreshContact(state: FreshDraftState, onProof: (proof: FreshProof | null) => void) {
  const email = state.payload!.current_details.client_email ?? "", phone = state.payload!.current_details.client_phone ?? "";
  const [proof, setProof] = useState<FreshProof | null>(() => state.draft?.phone_verification_id && state.draft.phone_verification_expires_at ? { id: state.draft.phone_verification_id, email, phone: normalizePhoneNumber(phone) ?? phone, expiresAt: Date.parse(state.draft.phone_verification_expires_at) } : null);
  const [challenge, setChallenge] = useState<{ id: string; email: string; phone: string; expiresAt: number; resendAt: number }>();
  const [code, setCode] = useState(""), [now, setNow] = useState(() => Date.now());
  const normalized = normalizePhoneNumber(phone);
  const valid = proof && proof.email === email.trim() && proof.phone === normalized && proof.expiresAt > now;
  useEffect(() => { onProof(valid ? proof : null); }, [valid, proof, onProof]);
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer); }, []);
  const request = () => {
    if (!normalized || !validContactEmail(email)) return;
    const contact = { email: email.trim(), phone: normalized };
    void state.flush().then(() => state.serialized(async (signal) => {
      const result = await state.api.requestCode(contact.email, contact.phone, signal);
      const receivedAt = Date.now();
      await state.syncContactRevision(signal);
      setProof(null);
      setChallenge({ id: result.challenge_id, ...contact, expiresAt: receivedAt + result.expires_in_seconds * 1000, resendAt: receivedAt + result.resend_after_seconds * 1000 }); setCode("");
    }, true)).catch(() => undefined);
  };
  const verify = () => {
    if (!challenge) return;
    void state.serialized(async (signal) => {
      const result = await state.api.verifyCode(challenge.id, code, signal);
      const receivedAt = Date.now();
      await state.syncContactRevision(signal);
      const next = { id: result.phone_verification_id, email: challenge.email, phone: result.phone_number, expiresAt: receivedAt + result.expires_in_seconds * 1000 };
      setProof(next); setChallenge(undefined); setCode("");
    }, true).catch(() => undefined);
  };
  const currentChallenge = challenge?.email === email.trim() && challenge?.phone === normalized ? challenge : undefined;
  const resend = Math.max(0, Math.ceil(((challenge?.resendAt ?? 0) - now) / 1000));
  return { email, phone, normalized, valid, code, setCode, now, challenge: currentChallenge, resend, request, verify };
}

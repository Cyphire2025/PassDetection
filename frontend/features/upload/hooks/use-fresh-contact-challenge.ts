"use client";

import { useEffect, useRef, useState } from "react";
import type { ApiError } from "@/lib/api/client";
import { validContactEmail } from "../services/contact-verification";
import type { FreshDraftState } from "./use-fresh-draft";

type ContactChallenge = {
  id: string;
  email: string;
  phone: string;
  expiresAt: number;
  resendAt: number;
};

/** Own a contact request from the first flush through its challenge or cooldown. */
export function useFreshContactChallenge(state: FreshDraftState, email: string, normalized: string | null) {
  const [challenge, setChallenge] = useState<ContactChallenge>();
  const [code, setCode] = useState("");
  const [now, setNow] = useState(() => Date.now());
  const [retry, setRetry] = useState<{ contact: string; at: number }>();
  const activeRequest = useRef<symbol | null>(null);
  const generation = useRef(0);
  const contactKey = JSON.stringify([email.trim(), normalized]);
  const retryAt = retry?.contact === contactKey ? retry.at : 0;
  const resendAt = Math.max(challenge?.resendAt ?? 0, retryAt);

  useEffect(() => {
    const epoch = ++generation.current;
    activeRequest.current = null;
    return () => { generation.current = epoch + 1; activeRequest.current = null; };
  }, [contactKey]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const request = () => {
    if (!normalized || !validContactEmail(email) || activeRequest.current || Date.now() < resendAt) return;
    const operation = Symbol("contact-request");
    const epoch = generation.current;
    const contact = { email: email.trim(), phone: normalized };
    activeRequest.current = operation;
    const isCurrent = () => activeRequest.current === operation && generation.current === epoch;
    let requested = false;

    void state.flush().then(() => state.serialized(async signal => {
      if (!isCurrent()) return;
      requested = true;
      const result = await state.api.requestCode(contact.email, contact.phone, signal);
      if (!isCurrent() || signal.aborted) return;
      const receivedAt = Date.now();
      setNow(receivedAt);
      setChallenge({ id: result.challenge_id, ...contact,
        expiresAt: receivedAt + result.expires_in_seconds * 1000,
        resendAt: receivedAt + result.resend_after_seconds * 1000 });
      setCode("");
    }, true)).catch((cause: unknown) => {
      const delay = (cause as Partial<ApiError> | undefined)?.retryAfterMs;
      if (requested && isCurrent() && typeof delay === "number" && Number.isFinite(delay) && delay > 0) {
        const receivedAt = Date.now();
        setNow(receivedAt);
        setRetry({ contact: contactKey, at: receivedAt + delay });
      }
    }).finally(() => {
      if (isCurrent()) activeRequest.current = null;
    });
  };

  return { challenge, setChallenge, code, setCode, now, request,
    resend: Math.max(0, Math.ceil((resendAt - now) / 1000)) };
}

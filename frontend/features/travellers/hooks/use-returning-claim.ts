"use client";

import { useEffect, useRef, useState } from "react";
import { returningApi } from "../api/returning.api";
import { resolveReturningTransition } from "../services/resolve-returning-transition";
import type { ClaimStart, ClaimTransition, DocumentQuestion, MaskedCandidates, PassportProof, ReturningHistory } from "../types";

/** The server selects the next verification stage. Client state never grants access. */
export function useReturningClaim() {
  const [transition, setTransition] = useState<ClaimTransition | null>(null);
  const [candidates, setCandidates] = useState<MaskedCandidates | null>(null);
  const [history, setHistory] = useState<ReturningHistory | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();
  const [resendAt, setResendAt] = useState(0);
  const [otpSent, setOtpSent] = useState(false);
  const method = useRef<ClaimStart["method"]>("phone");
  const groupToken = useRef<string | undefined>(undefined);
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);

  const run = async (operation: (signal: AbortSignal) => Promise<void>) => {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setPending(true);
    setError(undefined);
    try {
      await operation(controller.signal);
    } catch (cause) {
      if (!controller.signal.aborted) {
        const message = typeof cause === "object" && cause !== null && "message" in cause && typeof cause.message === "string"
          ? cause.message
          : "We could not complete this step. Please retry or upload current documents.";
        setError(message);
      }
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setPending(false);
    }
  };

  const accept = (next: ClaimTransition, signal: AbortSignal) => resolveReturningTransition(next, {
    method: method.current,
    groupToken: groupToken.current,
    signal,
    setTransition,
    setCandidates,
    setHistory,
  });
  const sendOtp = async (signal: AbortSignal) => {
    const result = await returningApi.requestOtp(signal);
    if (!signal.aborted) {
      setResendAt(Date.now() + result.resend_after_seconds * 1000);
      setOtpSent(true);
    }
  };

  return {
    transition, candidates, history, pending, error, resendAt, otpSent,
    start: (body: ClaimStart) => run(async (signal) => {
      method.current = body.method;
      groupToken.current = body.group_token;
      await accept(await returningApi.start(body, signal), signal);
      if (body.method === "phone" && !signal.aborted) await sendOtp(signal);
    }),
    requestOtp: () => run(sendOtp),
    verifyOtp: (code: string) => run(async (signal) => accept(await returningApi.verifyOtp(code, signal), signal)),
    select: (handle: string) => run(async (signal) => accept(await returningApi.selectCandidate(handle, signal), signal)),
    passport: (proof: PassportProof) => run(async (signal) => accept(await returningApi.passport(proof, signal), signal)),
    challenge: (answers: Partial<Record<DocumentQuestion, string>>) => run(async (signal) => accept(await returningApi.challenge(answers, signal), signal)),
    changeQuestion: (field: DocumentQuestion) => run(async (signal) => accept(await returningApi.changeQuestion(field, signal), signal)),
    confirm: (recover: boolean, actingFor: "self" | "family") => run(async (signal) => accept(await returningApi.confirm(recover, actingFor, signal), signal)),
    retryStage: () => run(async (signal) => {
      if (transition) await accept(transition, signal);
    }),
  };
}

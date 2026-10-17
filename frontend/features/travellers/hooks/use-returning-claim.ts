"use client";

import { useEffect, useRef, useState } from "react";
import { returningApi } from "../api/returning.api";
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
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);

  const run = async (operation: (signal: AbortSignal) => Promise<void>) => {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setPending(true);
    setError(undefined);
    try { await operation(controller.signal); }
    catch (cause) {
      if (!controller.signal.aborted) setError(typeof cause === "object" && cause !== null && "message" in cause && typeof cause.message === "string" ? cause.message : "We could not complete this step. Please retry or upload current documents.");
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setPending(false);
    }
  };

  const accept = async (next: ClaimTransition, signal: AbortSignal): Promise<void> => {
    if (signal.aborted) return;
    setTransition(next);
    if (next.stage === "identify") {
      if (method.current === "passport") return accept(await returningApi.passport({}, signal), signal);
      if (method.current === "code") { setTransition({ stage: "passport" }); return; }
      const people = await returningApi.candidates(signal);
      if (signal.aborted) return;
      setCandidates(people);
      setTransition({ stage: people.narrowing_required || people.items.length === 0 ? "passport" : "identify" });
      return;
    }
    if (next.stage === "review") {
      const details = await returningApi.history(signal);
      if (!signal.aborted) setHistory(details);
    }
    if (!signal.aborted) setTransition(next);
  };

  return {
    transition, candidates, history, pending, error, resendAt, otpSent,
    start: (body: ClaimStart) => run(async (signal) => { method.current = body.method; await accept(await returningApi.start(body, signal), signal); }),
    requestOtp: () => run(async (signal) => { const result = await returningApi.requestOtp(signal); if (!signal.aborted) { setResendAt(Date.now() + result.resend_after_seconds * 1000); setOtpSent(true); } }),
    verifyOtp: (code: string) => run(async (signal) => accept(await returningApi.verifyOtp(code, signal), signal)),
    select: (handle: string) => run(async (signal) => accept(await returningApi.selectCandidate(handle, signal), signal)),
    passport: (proof: PassportProof) => run(async (signal) => accept(await returningApi.passport(proof, signal), signal)),
    challenge: (answers: Partial<Record<DocumentQuestion, string>>) => run(async (signal) => accept(await returningApi.challenge(answers, signal), signal)),
    changeQuestion: (field: DocumentQuestion) => run(async (signal) => accept(await returningApi.changeQuestion(field, signal), signal)),
    confirm: (recover: boolean, actingFor: "self" | "family") => run(async (signal) => accept(await returningApi.confirm(recover, actingFor, signal), signal)),
    retryStage: () => run(async (signal) => { if (transition) await accept(transition, signal); }),
  };
}

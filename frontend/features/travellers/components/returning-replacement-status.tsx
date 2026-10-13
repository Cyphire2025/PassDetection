"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import type { PassportSubmission } from "@/types/passport.types";
import { returningApi } from "../api/returning.api";
import type { ReplacementIntent } from "../types";

/** A submitted fresh document remains a candidate until staff accepts it. */
export function ReturningReplacementStatus({ intent, submission }: { intent: ReplacementIntent; submission: PassportSubmission }) {
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<"pending" | "linked" | "failed">("pending");
  const [error, setError] = useState<string>();
  useEffect(() => {
    const controller = new AbortController();
    void returningApi.replacement({ source_submission_id: submission.id, expected_extraction_revision: submission.extraction_revision ?? 0, review_version: intent.reviewVersion, change_kind: intent.changeKind, idempotency_key: intent.idempotencyKey }, intent.uploadSessionId, controller.signal).then(() => {
      if (!controller.signal.aborted) setResult("linked");
    }).catch((cause) => {
      if (!controller.signal.aborted) { setResult("failed"); setError(typeof cause === "object" && cause !== null && "message" in cause && typeof cause.message === "string" ? cause.message : "The verified passport update could not be associated automatically."); }
    });
    return () => controller.abort();
  }, [attempt, intent, submission.id, submission.extraction_revision]);
  return <main className="flex min-h-dvh items-center justify-center bg-slate-50 p-4"><section className="w-full max-w-lg space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><h1 className="text-xl font-semibold text-slate-950">Updated document submitted</h1><p className="text-sm leading-6 text-slate-600">The current document for {intent.displayName} was submitted to the group.</p>{result === "pending" ? <p role="status" className="rounded-xl bg-blue-50 p-4 text-sm leading-6 text-blue-900">Associating this upload with the verified traveller… Keep this tab open.</p> : result === "linked" ? <p role="status" className="rounded-xl bg-amber-50 p-4 text-sm leading-6 text-amber-900">The update is linked to the traveller and is awaiting staff review. It has not replaced the accepted passport for future trips.</p> : <div role="alert" className="space-y-3 rounded-xl bg-amber-50 p-4 text-sm leading-6 text-amber-900"><p>{error}</p><p>The submitted document is saved. If your verification expired, ask your organiser to associate and review it. Retrying this step does not upload the document again.</p><Button type="button" variant="secondary" className="h-auto min-h-11 whitespace-normal" onClick={() => { setResult("pending"); setError(undefined); setAttempt((value) => value + 1); }}>Retry traveller association</Button></div>}</section></main>;
}

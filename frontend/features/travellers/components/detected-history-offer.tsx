"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { returningApi } from "../api/returning.api";

/** A yes/no hint from an owned extraction never carries stored identity or proof answers. */
export function DetectedHistoryOffer({ token, submissionId, extractionRevision, uploadSessionId, onVerify }: { token: string; submissionId: string; extractionRevision: number; uploadSessionId: string; onVerify: () => void }) {
  const [availableFor, setAvailableFor] = useState<string>();
  const requestKey = JSON.stringify([token, submissionId, extractionRevision, uploadSessionId]);
  useEffect(() => {
    const controller = new AbortController();
    void returningApi.detectedHistory({ group_token: token, source_submission_id: submissionId, expected_extraction_revision: extractionRevision }, uploadSessionId, controller.signal).then((result) => {
      if (!controller.signal.aborted && result.available) setAvailableFor(requestKey);
    }).catch(() => { /* An unavailable optional hint must not block the current upload. */ });
    return () => controller.abort();
  }, [token, submissionId, extractionRevision, uploadSessionId, requestKey]);
  if (availableFor !== requestKey) return null;
  return <aside className="mb-5 space-y-2 rounded-xl border border-blue-100 bg-blue-50 p-3"><p className="text-sm leading-6 text-blue-950">Saved traveller information may be available.</p><Button type="button" variant="secondary" className="h-auto min-h-11 whitespace-normal" onClick={onVerify}>Verify to review saved information</Button><p className="text-xs leading-5 text-blue-800">You can also continue with this upload.</p></aside>;
}

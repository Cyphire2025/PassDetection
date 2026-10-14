"use client";
import { useEffect, useState } from "react";
import { returningApi } from "../api/returning.api";
import type { ReturningHistory } from "../types";
import { ReturningReview } from "./returning-review";
import { TravellerShell } from "@/features/upload/components/traveller-shell";
import { Button } from "@/components/ui/button";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";

export function ReturningResume({ token, groupName, group, onFresh, onVerify }: { token: string; groupName: string; group?: UploadLinkResponse; onFresh: () => void; onVerify: () => void }) {
  const [history, setHistory] = useState<ReturningHistory>();
  const [verificationNeeded, setVerificationNeeded] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void returningApi.history(controller.signal, token).then((result) => { if (!controller.signal.aborted) setHistory(result); })
      .catch(() => { if (!controller.signal.aborted) setVerificationNeeded(true); });
    return () => controller.abort();
  }, [token]);
  if (history) return <ReturningReview history={history} groupName={groupName} group={group} groupToken={token} onFresh={onFresh} onReplace={onFresh} />;
  return <TravellerShell><section className="mt-10 space-y-4 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
    <h1 className="text-2xl font-semibold text-slate-950">Continue your saved draft</h1>
    {verificationNeeded ? <><p className="text-sm leading-6 text-slate-500">Your temporary draft stays saved for 24 hours. Verify your passport again to reopen your private details and continue.</p><Button type="button" className="min-h-12 w-full" onClick={onVerify}>Verify and continue</Button></> : <p role="status" className="text-sm text-slate-500">Opening your secure draft…</p>}
  </section></TravellerShell>;
}

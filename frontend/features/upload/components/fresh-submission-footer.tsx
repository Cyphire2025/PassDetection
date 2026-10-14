"use client";
import { Button } from "@/components/ui/button";
import type { FreshDraftState } from "../hooks/use-fresh-draft";

export function FreshSubmissionFooter({ state, error, verified, uploadBusy }: { state: FreshDraftState; error?: string; verified: boolean; uploadBusy: boolean }) {
  return <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5 sm:p-6" data-review-declaration>
    <p className="text-sm leading-6 text-slate-700">By submitting, you confirm that you have reviewed your passport and trip details and the information is correct.</p>
    <div className="mt-4 flex flex-col gap-4 border-t border-slate-100 pt-4 sm:flex-row sm:items-center sm:justify-between">
      <p className="text-xs leading-5 text-slate-500">{state.dirty ? "Saving your details…" : "Details saved privately for 24 hours."}<br />Unsubmitted images are not kept when you leave. Your travel team receives changes only when you submit.</p>
      <Button type="submit" className="min-h-12 shrink-0" disabled={state.pending || uploadBusy || !verified}>{uploadBusy ? "Preparing your documents…" : state.pending ? "Saving…" : "Confirm details and submit"}</Button>
    </div>
    {error && <p role="alert" className="mt-4 text-sm text-red-700">{error}</p>}
    {state.error && <div role="alert" className="mt-4 text-sm text-red-700">{state.error}<button type="button" onClick={state.retry} className="ml-2 min-h-11 font-semibold underline">Retry</button></div>}
  </section>;
}

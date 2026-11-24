"use client";
import type { Dispatch, SetStateAction } from "react";
import { CheckCircle2, Clock3 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { BrandLogo } from "@/components/brand/brand-logo";
import { TravellerShell } from "@/features/upload/components/traveller-shell";
import type { useReturningDraft } from "../hooks/use-returning-draft";
import type { CompletionResult } from "../types";
type DraftForm = ReturnType<typeof useReturningDraft>;

export function ReturningReviewSuccess({ result, draft, groupName, onFresh }: { result?: CompletionResult; draft: DraftForm["draft"]; groupName: string; onFresh: () => void }) {
  return (<TravellerShell>
    <BrandLogo className="mx-auto mb-6" priority />
    <section className="space-y-5 rounded-3xl border border-emerald-100 bg-white p-8 text-center shadow-sm">
      <CheckCircle2 className="mx-auto h-12 w-12 text-emerald-600" aria-hidden="true" />
      <h1 className="text-2xl font-semibold tracking-tight text-slate-950">Your trip details are saved</h1>
      <p className="text-sm leading-6 text-slate-500">Thank you. Your information for {groupName} has been submitted.{(result?.status ?? draft?.result_status) === "submitted" ? " Your travel team will review any remaining checks." : ""}
      </p>
      <Button
        type="button"
        variant="secondary"
        className="h-auto min-h-12 whitespace-normal"
        onClick={onFresh}
      >Continue for another traveller</Button>
    </section>
  </TravellerShell>);
}

export function ReturningReviewDeclaration({
  needsReplacement,
  needsContact,
  needsBack,
  confirmed,
  setConfirmed,
  form,
  extracting,
  uploadBusy,
  canSubmit
}: {
  needsReplacement: boolean;
  needsContact: boolean;
  needsBack: boolean;
  confirmed: boolean;
  setConfirmed: Dispatch<SetStateAction<boolean>>;
  form: DraftForm;
  extracting: boolean;
  uploadBusy: boolean;
  canSubmit: boolean
}) {
  return (<section
    className="mt-6 space-y-4 rounded-2xl border border-slate-200 bg-white p-5 sm:p-6"
    data-review-declaration
  >
    {needsReplacement && <p role="status" className="text-sm leading-6 text-amber-800">This saved passport needs an updated document before it can be used for this trip. Upload your current passport pages above.</p>}
    {needsContact && <p role="status" className="text-sm text-amber-800">Add and verify your current WhatsApp number before submitting.</p>}
    {needsBack && <p role="status" className="text-sm text-amber-800">Add the address page of your updated passport before submitting.</p>}
    <label className="flex cursor-pointer items-start gap-3 text-sm leading-6 text-slate-700">
      <input
        type="checkbox"
        required
        checked={confirmed}
        onChange={(event) => setConfirmed(event.target.checked)}
        disabled={form.pending || extracting || uploadBusy}
        className="mt-1 h-4 w-4 accent-blue-600"
      />I have reviewed my passport and trip details, and the information is correct.</label>
    <div
      className="flex flex-col gap-4 border-t border-slate-100 pt-4 sm:flex-row sm:items-center sm:justify-between"
    >
      <p role="status" className="flex items-start gap-2 text-xs leading-5 text-slate-500">
        <Clock3 className="mt-0.5 h-4 w-4 shrink-0" />
        <span>
          {form.dirty ? "Saving your details…" : "Details saved for 24 hours."}
          <br />Unsubmitted images are not kept when you leave. Your official record updates only after submission.</span>
      </p>
      <Button
        type="submit"
        className="min-h-12 px-6"
        disabled={!canSubmit || uploadBusy}
        isLoading={form.pending}
      >Submit trip details</Button>
    </div>
  </section>);
}

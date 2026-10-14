"use client";

import { useEffect, useRef, useState } from "react";
import { CheckCircle2, Clock3, MessageCircle, RefreshCw, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CustomDetailFields, CustomQuestionFields } from "@/features/upload/components/upload-flow-fields";
import { ReviewFields } from "@/features/upload/components/upload-flow-review";
import { TravellerShell } from "@/features/upload/components/traveller-shell";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import { useReturningDraft } from "../hooks/use-returning-draft";
import { returningApi } from "../api/returning.api";
import type { CompletionResult, ReplacementRequest, ReturningHistory, ReturningOwnedSource } from "../types";
import { ReturningContactDialog } from "./returning-contact-dialog";
import { ReturningCurrentDetails } from "./returning-current-details";
import { ReturningDraftImages } from "./returning-draft-images";
import { ReturningCollection } from "./returning-collection";
import { draftReviewReadiness } from "../services/draft-readiness";
import { requiredUploadSides } from "../services/draft-document-requirements";

type Props = { history: ReturningHistory; groupName: string; group?: UploadLinkResponse; groupToken?: string; onFresh: () => void; onReplace: (request: ReplacementRequest) => void; ownedSource?: ReturningOwnedSource; onCompleted?: (result: CompletionResult) => void };

export function ReturningReview(props: Props) {
  const [history, setHistory] = useState(props.history);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string>();
  const operation = useRef<AbortController | null>(null);
  useEffect(() => () => operation.current?.abort(), []);
  const reload = async (passportId?: string) => {
    if (operation.current) return;
    const controller = new AbortController(); operation.current = controller; setLoading(true); setLoadError(undefined);
    try {
      const result = passportId ? await returningApi.selectPassport(passportId, controller.signal, props.groupToken) : await returningApi.history(controller.signal, props.groupToken);
      if (!controller.signal.aborted) setHistory(result);
    } catch { if (!controller.signal.aborted) setLoadError("The latest details could not be loaded. Your draft is still saved; please retry."); }
    finally { operation.current = null; if (!controller.signal.aborted) setLoading(false); }
  };
  return <ReturningReviewContent key={history.review_version} {...props} history={history} loading={loading} loadError={loadError} reload={reload} />;
}

function ReturningReviewContent({ history, groupName, group, groupToken = "", ownedSource, onFresh, onCompleted, loading, loadError, reload }: Props & { loading: boolean; loadError?: string; reload: (id?: string) => Promise<void> }) {
  const form = useReturningDraft(history, groupToken, ownedSource);
  const [replacement, setReplacement] = useState(false);
  const [contactOpen, setContactOpen] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [result, setResult] = useState<CompletionResult>();
  const draft = form.draft;
  const payload = form.payload;
  const { extracting, frontChanged, contact, needsContact, needsReplacement, needsBack, canSubmit } = draftReviewReadiness(history, draft, form.pending, confirmed, group);
  const photoRequired = (history.missing_requirements ?? []).some((key) => key === "fresh_photo" || key === "visa_photo");
  const qualifierRequired = (history.missing_requirements ?? []).includes("qualifier_relationship");
  const passportRequired = replacement || frontChanged || needsReplacement || requiredUploadSides(history).some((side) => side !== "photo");
  if (result || draft?.status === "submitted") return <TravellerShell><section className="mt-12 space-y-5 rounded-3xl border border-emerald-100 bg-white p-8 text-center shadow-sm"><CheckCircle2 className="mx-auto h-12 w-12 text-emerald-600" aria-hidden="true" /><h1 className="text-2xl font-semibold tracking-tight text-slate-950">Your trip details are saved</h1><p className="text-sm leading-6 text-slate-500">Thank you. Your information for {groupName} has been submitted.{(result?.status ?? draft?.result_status) === "submitted" ? " Your travel team will review any remaining checks." : ""}</p><Button type="button" variant="secondary" className="h-auto min-h-12 whitespace-normal" onClick={onFresh}>Continue for another traveller</Button></section></TravellerShell>;
  return <TravellerShell wide>
    <header className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="max-w-2xl"><p className="text-sm font-medium text-blue-700">{groupName}</p><h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">Ready for your next journey</h1><p className="mt-3 text-sm leading-6 text-slate-500">Review your passport and complete this trip’s details. If your passport hasn’t changed, you don’t need to upload it again.</p></div>
      <span className="inline-flex w-fit shrink-0 items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-800"><CheckCircle2 className="h-4 w-4" />Passport verified</span>
    </header>
    {(history.available_passports?.length ?? 0) > 1 && <section className="mb-5 rounded-2xl border border-slate-200 bg-white p-4"><label htmlFor="trip-passport" className="text-sm font-medium text-slate-700">Passport for this trip</label><select id="trip-passport" value={history.passport?.id ?? ""} disabled={form.pending || loading} onChange={(event) => { const id = event.target.value; void form.flush().then(() => reload(id)).catch(() => undefined); }} className="mt-2 min-h-12 w-full rounded-xl border border-slate-200 bg-white px-3 text-base">{history.available_passports?.map((passport) => <option key={passport.id} value={passport.id}>{passport.number}{passport.is_default ? " · Usual passport" : ""}</option>)}</select></section>}
    {loadError && <p role="alert" className="mb-4 rounded-xl bg-red-50 p-4 text-sm text-red-800">{loadError}</p>}
    <div className="mb-6 flex flex-col gap-4 rounded-2xl border border-blue-100 bg-white/95 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
      <div><p className="font-medium text-slate-900">Has your passport changed?</p><p className="mt-1 text-sm leading-6 text-slate-500">Upload new pages only for a renewed passport, corrected document, or clearer copy.</p></div>
      <Button type="button" variant="secondary" className="h-auto min-h-12 shrink-0 whitespace-normal" disabled={!draft || form.pending} onClick={() => setReplacement(true)}><Upload className="h-4 w-4" />Upload updated passport</Button>
    </div>
    {form.error && <div role="alert" className="mb-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-800">{form.error}<button type="button" onClick={form.retry} className="ml-3 min-h-10 font-semibold underline">Retry</button><button type="button" disabled={loading} onClick={() => void reload()} className="ml-3 min-h-10 font-semibold underline">Refresh current trip requirements</button></div>}
    {!draft || !payload ? <div role="status" className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">Preparing your secure review…</div> : <form onSubmit={(event) => {
      event.preventDefault(); if (!canSubmit) return;
      void form.complete().then((saved) => { setResult(saved); onCompleted?.(saved); }).catch(() => undefined);
    }}>
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
        <div className="min-w-0 space-y-5">
          {passportRequired && <ReturningCollection form={form} group={group} token={groupToken} photo={false} qualifier={false} passport frontFirst={replacement || frontChanged || needsReplacement} onChange={() => setConfirmed(false)} />}
          <ReturningDraftImages documents={history.documents} draft={draft} hidePhoto={photoRequired} />
          {(photoRequired || qualifierRequired) && <ReturningCollection form={form} group={group} token={groupToken} photo={photoRequired} qualifier={qualifierRequired} onChange={() => setConfirmed(false)} />}
        </div>
        <div className="min-w-0 space-y-5">
          <section className="rounded-2xl border border-slate-200 bg-white p-5 sm:p-6">
            <div className="mb-5 flex items-center justify-between gap-3"><div><p className="text-xs font-medium uppercase tracking-wider text-slate-400">Passport details</p><h2 className="mt-1 break-words text-lg font-semibold text-slate-950">{history.display_name}</h2></div><span className="rounded-full bg-slate-50 px-3 py-1 text-xs text-slate-500">Review & edit</span></div>
            {extracting && <p role="status" className="mb-4 flex items-center gap-2 rounded-xl bg-blue-50 p-3 text-sm text-blue-800"><RefreshCw className="h-4 w-4 animate-spin" />Reading your updated details page…</p>}
            {draft.extraction_status === "failed" && <p role="alert" className="mb-4 rounded-xl bg-amber-50 p-3 text-sm leading-6 text-amber-900">We couldn’t read this page reliably. Upload a clearer details page to continue.</p>}
            <fieldset disabled={form.pending || extracting}><ReviewFields fields={payload.passport_fields} onChange={(key, value) => { setConfirmed(false); form.update("passport_fields", key, value); }} /></fieldset>
            <p className="mt-4 text-xs leading-5 text-slate-500">Check that these details match the document shown. Changes stay in your draft until you submit.</p>
          </section>
          <section className="rounded-2xl border border-blue-200 bg-blue-50/80 p-5 sm:p-6">
            <div className="flex items-start gap-3"><MessageCircle className="mt-0.5 h-5 w-5 shrink-0 text-blue-600" /><div className="min-w-0 flex-1"><h2 className="text-sm font-semibold text-slate-950">Current WhatsApp contact</h2><p className="mt-2 break-words text-lg font-semibold text-slate-900">{contact || "Add your current number"}</p><p className="mt-1 text-xs leading-5 text-slate-600">{draft.verified_phone ? "Verified for this draft. Your contact updates when you submit." : "Use the number you want your travel team to contact for this trip."}</p></div></div>
            <Button type="button" variant="secondary" className="mt-4 min-h-11" disabled={form.pending} onClick={() => { void form.flush().then(() => setContactOpen(true)).catch(() => undefined); }}>{contact ? "Change WhatsApp number" : "Add WhatsApp number"}</Button>
          </section>
          <section className="rounded-2xl border border-slate-200 bg-white p-5 sm:p-6">
            <h2 className="text-lg font-semibold text-slate-950">Details for this trip</h2><p className="mt-1 text-sm leading-6 text-slate-500">Please complete the information requested by your travel team.</p>
            <fieldset disabled={form.pending}>
              <ReturningCurrentDetails fields={history.group_requirements.current_detail_fields ?? []} values={payload.current_details} onChange={(key, value) => { setConfirmed(false); form.update("current_details", key, value); }} />
              <CustomQuestionFields questions={history.group_requirements.custom_questions.filter((question) => question.enabled)} answers={payload.custom_answers} onChange={(key, value) => { setConfirmed(false); form.update("custom_answers", key, value); }} />
              <CustomDetailFields details={history.group_requirements.custom_details.filter((detail) => detail.enabled)} answers={payload.custom_detail_answers} onChange={(key, value) => { setConfirmed(false); form.update("custom_detail_answers", key, value); }} />
            </fieldset>
          </section>
        </div>
      </div>
      <section className="mt-6 space-y-4 rounded-2xl border border-slate-200 bg-white p-5 sm:p-6">
        {needsReplacement && <p role="status" className="text-sm leading-6 text-amber-800">This saved passport needs an updated document before it can be used for this trip. Upload your current passport pages above.</p>}
        {needsContact && <p role="status" className="text-sm text-amber-800">Add and verify your current WhatsApp number before submitting.</p>}
        {needsBack && <p role="status" className="text-sm text-amber-800">Add the address page of your updated passport before submitting.</p>}
        <label className="flex cursor-pointer items-start gap-3 text-sm leading-6 text-slate-700"><input type="checkbox" required checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} disabled={form.pending || extracting} className="mt-1 h-4 w-4 accent-blue-600" />I have reviewed my passport and trip details, and the information is correct.</label>
        <div className="flex flex-col gap-4 border-t border-slate-100 pt-4 sm:flex-row sm:items-center sm:justify-between"><p role="status" className="flex items-start gap-2 text-xs leading-5 text-slate-500"><Clock3 className="mt-0.5 h-4 w-4 shrink-0" /><span>{form.dirty ? "Saving your draft…" : "Draft saved for 24 hours."}<br />Your official record updates only after submission.</span></p><Button type="submit" className="min-h-12 px-6" disabled={!canSubmit} isLoading={form.pending}>Submit trip details</Button></div>
      </section>
    </form>}
    {contactOpen && draft && <ReturningContactDialog draftId={draft.id} onClose={() => setContactOpen(false)} onSaved={() => { setConfirmed(false); setContactOpen(false); void form.refresh().catch(() => undefined); }} />}
  </TravellerShell>;
}

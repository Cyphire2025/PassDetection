"use client";

import { useEffect, useRef, useState } from "react";
import { CheckCircle2, FileImage } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CustomDetailFields, CustomQuestionFields } from "@/features/upload/components/upload-flow-fields";
import { formatPassportCountry } from "@/lib/utils/passport-country";
import { toLabel } from "@/features/upload/services/upload-flow-helpers";
import { returningApi } from "../api/returning.api";
import type { CompletionResult, ReplacementRequest, ReturningDocument, ReturningHistory } from "../types";
import { ReturningDocumentPreview } from "./returning-document-preview";
import { ReturningContactDialog } from "./returning-contact-dialog";
import { ReturningCurrentDetails } from "./returning-current-details";
import { ReturningUpdateDialog } from "./returning-update-dialog";

const SUITABILITY_TEXT: Record<ReturningHistory["suitability"]["outcome"], string> = {
  suitable: "Suitable under the currently checked itinerary rules",
  replacement_required: "A replacement passport is required",
  review_required: "Your travel team needs to review document suitability",
  cannot_assess: "Document suitability still needs assessment",
};

export function ReturningReview({ history: initialHistory, groupName, onFresh, onReplace }: { history: ReturningHistory; groupName: string; onFresh: () => void; onReplace: (request: ReplacementRequest) => void }) {
  const [history, setHistory] = useState(initialHistory);
  const [answers, setAnswers] = useState<Record<string, string>>(() => initialHistory.saved_answers?.custom_answers ?? {});
  const [details, setDetails] = useState<Record<string, string>>(() => initialHistory.saved_answers?.custom_detail_answers ?? {});
  const [currentDetails, setCurrentDetails] = useState<Record<string, string>>(() => initialHistory.saved_answers?.current_details ?? {});
  const [confirmed, setConfirmed] = useState(false);
  const [viewed, setViewed] = useState<Set<string>>(() => new Set());
  const [preview, setPreview] = useState<ReturningDocument | null>(null);
  const [contactOpen, setContactOpen] = useState(false);
  const [updateOpen, setUpdateOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();
  const [stale, setStale] = useState(false);
  const [result, setResult] = useState<CompletionResult | null>(null);
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const operation = useRef<AbortController | null>(null);
  useEffect(() => () => operation.current?.abort(), []);
  const requirements = history.group_requirements;
  const questions = requirements.custom_questions.filter((question) => question.enabled);
  const customDetails = requirements.custom_details.filter((detail) => detail.enabled);
  const unavailable = history.documents.some((document) => !document.available);
  const needsFresh = !history.passport || !history.documents.length || requirements.require_selfie || unavailable || history.missing_requirements?.length || history.suitability.outcome === "replacement_required";
  const allDocumentsViewed = history.documents.every((document) => document.available && viewed.has(document.id));
  const fields = history.extracted_fields ? Object.entries(history.extracted_fields).map(([key, value]) => [key === "issuing_country" ? "Issuing country" : toLabel(key), key === "issuing_country" || key === "nationality" ? formatPassportCountry(value) : value]) : history.passport ? [
    ["Passport number", history.passport.number], ["Issuing country", formatPassportCountry(history.passport.issuing_country)],
    ["Date of birth", history.passport.date_of_birth], ["Issue date", history.passport.issue_date], ["Expiry date", history.passport.expiry_date],
  ] : [];
  const refreshReview = async (passportId?: string) => {
    if (operation.current) return;
    const controller = new AbortController(); operation.current = controller; setPending(true);
    try {
      const updated = passportId ? await returningApi.selectPassport(passportId, controller.signal) : await returningApi.history(controller.signal);
      if (controller.signal.aborted) return;
      setHistory(updated);
      if (!passportId || updated.question_version !== history.question_version) {
        setAnswers(updated.saved_answers?.custom_answers ?? {});
        setDetails(updated.saved_answers?.custom_detail_answers ?? {});
        setCurrentDetails(updated.saved_answers?.current_details ?? {});
      }
      setConfirmed(false); setViewed(new Set()); setPreview(null); setStale(false); setError(undefined);
    } catch { if (!controller.signal.aborted) { if (passportId) { setStale(true); setConfirmed(false); } setError("The latest review could not be loaded. Retry or upload current documents."); } }
    finally { operation.current = null; if (!controller.signal.aborted) setPending(false); }
  };
  if (result) return <main className="flex min-h-dvh items-center justify-center bg-slate-50 p-5"><section className="w-full max-w-md space-y-4 rounded-2xl border border-emerald-100 bg-white p-6 text-center shadow-sm"><CheckCircle2 className="mx-auto h-12 w-12 text-emerald-600" aria-hidden="true" /><h1 className="text-xl font-semibold text-slate-950">{result.status === "accepted" ? "Trip information accepted" : "Trip information submitted"}</h1><p className="text-sm leading-6 text-slate-600">Your information for {groupName} has been saved.{result.status === "submitted" ? " Your travel team will review the remaining checks." : ""}</p><Button type="button" variant="secondary" className="h-auto min-h-11 whitespace-normal" onClick={onFresh}>Continue for another traveller</Button></section></main>;

  return <main className="min-h-dvh bg-slate-50 px-3 py-5 sm:p-8"><div className="mx-auto max-w-4xl space-y-5">
    <header><p className="text-sm font-medium text-blue-700">{groupName}</p><h1 className="mt-1 text-2xl font-semibold text-slate-950">Review your saved passport</h1><p className="mt-2 text-sm leading-6 text-slate-600">Check the passport images and every detail below. If your passport has changed, upload the updated document before continuing.</p></header>
    <div className="flex flex-col items-stretch gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 sm:flex-row sm:items-center sm:justify-between"><p className="min-w-0 flex-1 text-sm leading-6 text-amber-900">Renewed passport, corrected details, or a better scan? Upload the current version for review.</p><Button type="button" variant="secondary" className="h-auto min-h-11 whitespace-normal" onClick={() => setUpdateOpen(true)} disabled={pending}>Upload updated passport</Button></div>
    {(history.available_passports?.length ?? 0) > 1 && <section className="rounded-xl border border-slate-200 bg-white p-4"><label htmlFor="trip-passport" className="text-sm font-semibold text-slate-900">Passport for this trip</label><select id="trip-passport" value={history.passport?.id ?? ""} disabled={pending} onChange={(event) => void refreshReview(event.target.value)} className="mt-2 min-h-12 w-full min-w-0 rounded-lg border border-slate-300 bg-white px-3 text-sm focus-visible:ring-2 focus-visible:ring-blue-600">{history.available_passports?.map((passport) => <option key={passport.id} value={passport.id}>{passport.number} · {formatPassportCountry(passport.issuing_country)}{passport.is_default ? " · Usual passport" : ""}</option>)}</select><p className="mt-2 text-xs leading-5 text-slate-500">Choose an accepted passport for this trip, then review its images and details. This does not change your usual passport.</p></section>}
    <form className="space-y-5" onSubmit={async (event) => {
      event.preventDefault();
      if (operation.current || stale || needsFresh || !confirmed || !allDocumentsViewed) return;
      const controller = new AbortController(); operation.current = controller; setPending(true); setError(undefined);
      try {
        const saved = await returningApi.complete({ question_version: history.question_version, review_version: history.review_version, ...(history.participation_revision !== null ? { expected_participation_revision: history.participation_revision } : {}), custom_answers: answers, custom_detail_answers: details, current_details: currentDetails, information_confirmed: true, idempotency_key: idempotencyKey }, controller.signal);
        if (!controller.signal.aborted) setResult(saved);
      } catch (cause) { if (!controller.signal.aborted && typeof cause === "object" && cause !== null && "status" in cause && cause.status === 409) { setStale(true); setConfirmed(false); } if (!controller.signal.aborted) setError(typeof cause === "object" && cause !== null && "message" in cause && typeof cause.message === "string" ? cause.message : "Your submission could not be confirmed. Keep this page open and retry; your answers remain here."); }
      finally { operation.current = null; if (!controller.signal.aborted) setPending(false); }
    }}>
      <div className="grid items-start gap-5 md:grid-cols-2">
        <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-4 sm:p-5"><h2 className="text-lg font-semibold text-slate-950">Passport images</h2><p className="text-xs leading-5 text-slate-500">Open each available image to compare it with the saved details.</p><ul className="space-y-2">{history.documents.map((document) => <li key={document.id}><Button type="button" variant="secondary" className="h-auto min-h-12 w-full justify-start whitespace-normal py-3 text-left" disabled={!document.available || pending} onClick={() => setPreview(document)}><FileImage className="h-4 w-4 shrink-0" aria-hidden="true" /><span>{document.label}{!document.available ? " · Unavailable" : viewed.has(document.id) ? " · Viewed" : " · Open preview"}</span></Button></li>)}</ul>{!history.documents.length && <p className="text-sm text-slate-500">No retained document images are available.</p>}{preview && <ReturningDocumentPreview key={preview.id} document={preview} onViewed={(id) => setViewed((current) => new Set(current).add(id))} onClose={() => setPreview(null)} />}</section>
        <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-4 sm:p-5"><h2 className="text-lg font-semibold text-slate-950">{history.display_name}</h2><dl className="space-y-3">{fields.map(([label, value]) => <div key={label}><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 break-words text-sm font-medium text-slate-900">{value ?? "Not available"}</dd></div>)}<div><dt className="text-xs text-slate-500">Current contact</dt><dd className="mt-1 break-words text-sm font-medium text-slate-900">{history.contact_phone || "Not recorded"}</dd></div></dl><Button type="button" variant="secondary" className="min-h-11" onClick={() => setContactOpen(true)} disabled={pending}>Change WhatsApp contact</Button><p role="status" className={`rounded-xl p-3 text-sm leading-6 ${history.suitability.outcome === "suitable" ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-900"}`}>{SUITABILITY_TEXT[history.suitability.outcome]}</p></section>
      </div>
      <section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5"><h2 className="text-lg font-semibold text-slate-950">This trip’s details</h2><p className="mt-1 text-sm leading-6 text-slate-500">Answer the current questions for this trip. Only unchanged answers from this current trip are retained. Answers from earlier trips are not carried over.</p><fieldset disabled={pending}><ReturningCurrentDetails fields={requirements.current_detail_fields ?? []} values={currentDetails} onChange={(key, value) => setCurrentDetails((current) => ({ ...current, [key]: value }))} /><CustomQuestionFields questions={questions} answers={answers} onChange={(id, value) => setAnswers((current) => ({ ...current, [id]: value }))} /><CustomDetailFields details={customDetails} answers={details} onChange={(id, value) => setDetails((current) => ({ ...current, [id]: value }))} /></fieldset>{!questions.length && !customDetails.length && !requirements.current_detail_fields?.length && <p className="mt-3 text-sm text-slate-600">No additional questions are required for this group.</p>}</section>
      {Boolean(needsFresh) && <div role="status" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900">This trip needs {requirements.require_selfie ? "a fresh photo or live capture" : unavailable ? "a current copy of an unavailable document" : "additional current documents or details"}. Continue with current document collection to complete those requirements.</div>}
      {error && <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">{error}</div>}
      {stale && <Button type="button" variant="secondary" className="h-auto min-h-11 whitespace-normal" onClick={() => void refreshReview()} disabled={pending}>Refresh current trip requirements</Button>}
      <label className="flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-4 text-sm leading-6 text-slate-700"><input type="checkbox" required checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} disabled={pending} className="mt-1" />I reviewed the images and details. This passport is still current and these answers apply to this trip.</label>
      {!allDocumentsViewed && <p className="text-sm text-slate-600">Open each available document preview before submitting.</p>}
      <div className="flex flex-col gap-3 sm:flex-row sm:justify-end"><Button type="button" variant="secondary" className="h-auto min-h-12 whitespace-normal" onClick={onFresh} disabled={pending}>Upload current documents</Button><Button type="submit" className="min-h-12" disabled={Boolean(needsFresh) || stale || !confirmed || !allDocumentsViewed} isLoading={pending}>Submit this trip’s information</Button></div>
    </form>
    {contactOpen && <ReturningContactDialog onClose={() => setContactOpen(false)} onSaved={(updated) => { setHistory(updated); if (updated.question_version !== history.question_version) { setAnswers(updated.saved_answers?.custom_answers ?? {}); setDetails(updated.saved_answers?.custom_detail_answers ?? {}); setCurrentDetails(updated.saved_answers?.current_details ?? {}); } setConfirmed(false); setViewed(new Set()); setPreview(null); setContactOpen(false); }} />}
    {updateOpen && <ReturningUpdateDialog history={history} onClose={() => setUpdateOpen(false)} onContinue={onReplace} />}
  </div></main>;
}






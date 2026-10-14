"use client";
import { useEffect, useState } from "react";
import { ArrowLeft, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import type { FreshMemberResume } from "@/features/travellers/services/draft-resume";
import type { FreshCollection } from "../api/fresh-draft.api";
import { useFreshDraft } from "../hooks/use-fresh-draft";
import { getUploadFlowSettings } from "../services/configured-upload";
import { freshValidation } from "../services/fresh-validation";
import { CenteredLoader } from "./upload-flow-shell";
import { ReviewFields } from "./upload-flow-review";
import { FreshDocuments } from "./fresh-documents";
import { FreshTripFields } from "./fresh-trip-fields";
import { FreshContact, type FreshProof } from "./fresh-contact";
import { FreshQualifier } from "./fresh-qualifier";
import { ReviewDetailsColumn } from "./review-details-column";
import { FreshSubmissionFooter } from "./fresh-submission-footer";
export function FreshMemberForm({ token, group, member, initial, onStarted, onComplete, onBack }: { token: string; group: UploadLinkResponse; member: FreshMemberResume; initial: FreshCollection; onStarted: (expires: string) => void; onComplete: () => void; onBack: () => void }) {
  const state = useFreshDraft(token, member, initial);
  const settings = getUploadFlowSettings(group);
  const [proof, setProof] = useState<FreshProof | null>(null), [error, setError] = useState<string>();
  const [uploadBusy, setUploadBusy] = useState(false);
  const expires = state.draft?.expires_at;
  useEffect(() => { if (expires) onStarted(expires); }, [expires, onStarted]);
  if (state.draft?.status === "submitted") return <section className="rounded-2xl border border-emerald-100 bg-white p-8 text-center"><CheckCircle2 className="mx-auto h-12 w-12 text-emerald-600" /><h2 className="mt-4 text-2xl font-semibold text-slate-950">Details submitted</h2><p className="mt-2 text-sm text-slate-500">Your travel team has received this traveller’s details.</p><Button type="button" className="mt-6" onClick={onComplete}>Continue</Button></section>;
  if (!state.payload || !state.draft) return <><Button type="button" variant="ghost" onClick={onBack}>Back</Button>{state.error ? <div role="alert" className="rounded-xl bg-white p-5 text-red-700">{state.error}<Button className="ml-3" type="button" variant="secondary" onClick={state.retry}>Retry</Button></div> : <CenteredLoader />}</>;
  const submit = async () => {
    if (uploadBusy) return;
    const invalid = freshValidation(settings, state.payload!, state.draft!);
    setError(invalid ?? undefined); if (invalid) return;
    if (!proof || proof.expiresAt <= Date.now()) { setError("Verify your WhatsApp number before submitting."); return; }
    if (initial.submission_mode === "family" && initial.family_member_index === 0) state.collection({
      family_head_name: [state.payload!.passport_fields.given_names, state.payload!.passport_fields.surname].filter(Boolean).join(" ") || state.payload!.current_details.client_name,
      family_head_email: state.payload!.current_details.client_email, family_head_phone: state.payload!.current_details.client_phone,
    });
    try { await state.complete(proof.id); onComplete(); } catch { /* Hook presents the authoritative error and keeps the same submission key. */ }
  };
  const hasPassport = state.draft.documents.some((document) => document.side === "front");
  return <div className="space-y-5">
    <button type="button" disabled={state.pending || uploadBusy} onClick={() => { void state.leave().then(onBack).catch(() => undefined); }} className="inline-flex min-h-11 items-center gap-2 text-sm font-medium text-slate-600 hover:text-blue-700"><ArrowLeft className="h-4 w-4" />Back</button>
    {settings.relationWithQualifierEnabled && <FreshQualifier state={state} group={group} />}
    <form onSubmit={(event) => { event.preventDefault(); void submit(); }}>
    <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
      <FreshDocuments state={state} settings={settings} token={token} sessionId={member.sessionId} onUploadBusyChange={setUploadBusy} />
      <ReviewDetailsColumn><section className="min-w-0 rounded-2xl border border-slate-200 bg-white p-4 sm:p-6">
        <fieldset disabled={state.pending} className="min-w-0">
          <div className="mb-5"><h2 className="text-xl font-semibold tracking-tight text-slate-950">Review your details</h2><p className="mt-2 text-sm leading-6 text-slate-500">Check the details against your documents. You can edit them or replace an image before submitting.</p></div>
          {hasPassport ? <ReviewFields fields={state.payload.passport_fields} onChange={(key, value) => state.update("passport_fields", key, value)} /> : <label className="block text-sm font-medium text-slate-700">Full name<input className="mt-2 h-12 w-full rounded-xl border border-slate-200 px-3 text-base" value={state.payload.current_details.client_name ?? ""} onChange={(event) => state.update("current_details", "client_name", event.target.value)} required maxLength={255} /></label>}
          {(state.draft.extraction_status === "pending" || state.draft.extraction_status === "running") && <p role="status" className="mt-3 text-sm text-blue-700">Reading your passport… You can complete the trip details below while we check it.</p>}
          {state.draft.extraction_status === "failed" && <p role="alert" className="mt-3 text-sm text-red-700">We couldn’t read this passport clearly. Replace the details page with a clearer image.</p>}
          <FreshTripFields state={state} settings={settings} memberIndex={initial.family_member_index ?? 0} />
          <FreshContact state={state} onProof={setProof} />
        </fieldset>
      </section></ReviewDetailsColumn>
    </div>
    <FreshSubmissionFooter state={state} error={error} verified={Boolean(proof)} uploadBusy={uploadBusy} />
    </form>
  </div>;
}

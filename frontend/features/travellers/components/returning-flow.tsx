"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import { normalizePhoneNumber, PHONE_FORMAT_HELP } from "@/lib/utils/phone-number";
import { isValidPassportIsoDate } from "@/lib/utils/passport-date";
import { UploadHeader } from "@/features/upload/components/upload-flow-shell";
import { useReturningClaim } from "../hooks/use-returning-claim";
import type { DocumentQuestion, ReplacementRequest, ReturningCapabilities, ReturningMethod } from "../types";
import { DocumentQuestionFields, PassportProofFields, QUESTION_LABELS } from "./returning-fields";
import { ReturningReview } from "./returning-review";

export function ReturningFlow({ token, group, initialMethod, capabilities, onFresh, onReplace }: { token: string; group: UploadLinkResponse; initialMethod: ReturningMethod; capabilities: ReturningCapabilities; onFresh: () => void; onReplace: (request: ReplacementRequest) => void }) {
  const claim = useReturningClaim();
  const [phone, setPhone] = useState("");
  const [passport, setPassport] = useState("");
  const [issuer, setIssuer] = useState("");
  const [code, setCode] = useState("");
  const [otp, setOtp] = useState("");
  const [answers, setAnswers] = useState<Partial<Record<DocumentQuestion, string>>>({});
  const [actingFor, setActingFor] = useState<"self" | "family">("self");
  const [confirmed, setConfirmed] = useState(false);
  const [now, setNow] = useState(0);
  const stage = claim.transition?.stage;
  const resendIn = Math.max(0, Math.ceil((claim.resendAt - now) / 1000));
  useEffect(() => { if (!claim.resendAt) return; const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer); }, [claim.resendAt]);
  if (stage === "review" && claim.history) return <ReturningReview history={claim.history} groupName={group.name} onFresh={onFresh} onReplace={onReplace} />;
  const questions = claim.transition?.questions ?? [];
  const heading = !stage ? initialMethod === "phone" ? "Verify your WhatsApp number" : initialMethod === "passport" ? "Find your saved passport" : `Enter your ${capabilities.code_label ?? "individual code"}` : stage === "contact" ? "WhatsApp verification" : stage === "identify" ? "Choose the traveller" : stage === "passport" ? "Confirm the full passport" : stage === "challenge" ? "Check your passport details" : "Confirm access";

  return <main className="min-h-dvh bg-slate-50 px-3 py-5 sm:px-6 sm:py-10"><div className="mx-auto max-w-lg">
    <UploadHeader groupName={group.name} departureDate={group.travel_date} returnDate={group.return_date} />
    <section className="space-y-5 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6" aria-busy={claim.pending}>
      <div><p className="text-xs font-semibold uppercase tracking-wide text-blue-700">Returning traveller</p><h2 className="mt-1 text-xl font-semibold text-slate-950">{heading}</h2><p className="mt-2 text-sm leading-6 text-slate-500">Your passport details stay locked until the required checks are complete.</p></div>
      {claim.error && <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm leading-6 text-red-800">{claim.error}</div>}
      {!stage && <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); void claim.start({ group_token: token, method: initialMethod, document_type: "P", ...(initialMethod === "phone" ? { phone_number: normalizePhoneNumber(phone) ?? phone } : {}), ...(initialMethod === "passport" ? { passport_number: passport, issuing_country: issuer } : {}), ...(initialMethod === "code" ? { individual_code: code } : {}) }); }}>
        {initialMethod === "phone" && <Input label="WhatsApp number" type="tel" autoComplete="tel" value={phone} onChange={(event) => setPhone(event.target.value)} required maxLength={64} hint={PHONE_FORMAT_HELP} disabled={claim.pending} className="h-12 text-base" />}
        {initialMethod === "passport" && <PassportProofFields number={passport} issuer={issuer} onNumber={setPassport} onIssuer={setIssuer} disabled={claim.pending} />}
        {initialMethod === "code" && <Input label={capabilities.code_label ?? "Individual code"} value={code} onChange={(event) => setCode(event.target.value)} maxLength={128} required autoComplete="off" disabled={claim.pending} hint="Enter the individual code exactly, including any leading zeros." className="h-12 text-base" />}
        <Button type="submit" className="min-h-12 w-full" isLoading={claim.pending} disabled={initialMethod === "phone" && !normalizePhoneNumber(phone)}>Continue</Button>
      </form>}
      {stage === "contact" && <div className="space-y-4"><p className="text-sm leading-6 text-slate-600">Request a one-time code on the WhatsApp number you entered.</p>
        <Button type="button" variant="secondary" className="min-h-11 w-full" disabled={claim.pending || (claim.otpSent && resendIn > 0)} onClick={() => { setNow(Date.now()); void claim.requestOtp(); }}>{claim.otpSent ? resendIn > 0 ? `Resend available in ${resendIn}s` : "Resend code" : "Send WhatsApp code"}</Button>
        {claim.otpSent && <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); void claim.verifyOtp(otp); }}><Input label="WhatsApp verification code" value={otp} onChange={(event) => setOtp(event.target.value.replace(/\D/g, ""))} required inputMode="numeric" autoComplete="one-time-code" minLength={6} maxLength={6} disabled={claim.pending} className="h-12 text-base tracking-widest" /><Button type="submit" isLoading={claim.pending} disabled={otp.length !== 6} className="min-h-12 w-full">Verify code</Button></form>}
      </div>}
      {((stage === "identify" && !claim.candidates) || stage === "review") && <Button type="button" className="min-h-12 w-full" isLoading={claim.pending} onClick={() => void claim.retryStage()}>Retry loading verified step</Button>}
      {stage === "identify" && claim.candidates && <div className="space-y-3"><p className="text-sm leading-6 text-slate-600">Choose the intended person, then enter their full passport number. Each person needs their own check.</p><ul className="space-y-2">{claim.candidates?.items.map((person) => <li key={person.handle}><Button type="button" variant="secondary" className="h-auto min-h-12 w-full justify-between whitespace-normal py-3 text-left" disabled={claim.pending} onClick={() => void claim.select(person.handle)}><span>{person.label}</span><span className="text-xs text-slate-500">{person.passport_hint}</span></Button></li>)}</ul></div>}
      {stage === "passport" && <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); void claim.passport({ passport_number: passport, issuing_country: issuer, document_type: "P" }); }}><PassportProofFields number={passport} issuer={issuer} onNumber={setPassport} onIssuer={setIssuer} disabled={claim.pending} /><Button type="submit" isLoading={claim.pending} className="min-h-12 w-full">Check passport</Button></form>}
      {stage === "challenge" && <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); void claim.challenge(Object.fromEntries(questions.map((field) => [field, answers[field] ?? ""]))); }}>
        <DocumentQuestionFields questions={questions} answers={answers} onChange={(field, value) => setAnswers((current) => ({ ...current, [field]: value }))} disabled={claim.pending} />
        {claim.transition?.can_change_question && <label className="block space-y-2 text-sm text-slate-600">Use another passport date<select aria-label="Change verification question" value="" disabled={claim.pending} onChange={(event) => { if (event.target.value) void claim.changeQuestion(event.target.value as DocumentQuestion); }} className="min-h-11 w-full rounded-xl border border-slate-300 bg-white px-3 text-sm"><option value="">Choose another reliable date</option>{(claim.transition.available_questions ?? []).filter((field) => !questions.includes(field)).map((field) => <option key={field} value={field}>{QUESTION_LABELS[field]}</option>)}</select></label>}
        <Button type="submit" isLoading={claim.pending} disabled={!questions.length || questions.some((field) => !isValidPassportIsoDate(answers[field] ?? ""))} className="min-h-12 w-full">Verify passport details</Button>
      </form>}
      {(stage === "confirm" || stage === "recovery") && <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); void claim.confirm(stage === "recovery", actingFor); }}>
        <fieldset className="space-y-3"><legend className="mb-2 text-sm font-medium text-slate-700">Who are you submitting for?</legend><label className="flex items-center gap-3 text-sm"><input type="radio" name="returning-actor" checked={actingFor === "self"} onChange={() => setActingFor("self")} />Myself</label><label className="flex items-center gap-3 text-sm"><input type="radio" name="returning-actor" checked={actingFor === "family"} onChange={() => setActingFor("family")} />A family member I am authorised to help</label></fieldset>
        {stage === "recovery" && <p className="rounded-xl bg-amber-50 p-3 text-sm leading-6 text-amber-900">The verified number will become this traveller’s current contact for future trips. Other people sharing either number are unaffected.</p>}
        <label className="flex items-start gap-3 text-sm leading-6 text-slate-700"><input type="checkbox" required checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} className="mt-1" />I have permission to view and confirm this traveller’s information.</label>
        <Button type="submit" disabled={!confirmed} isLoading={claim.pending} className="min-h-12 w-full">Review saved details</Button>
      </form>}
      <div className="border-t border-slate-100 pt-4"><Button type="button" variant="ghost" className="h-auto min-h-11 w-full whitespace-normal" onClick={onFresh} disabled={claim.pending}>New traveller / Upload current documents</Button><p className="mt-2 text-center text-xs leading-5 text-slate-500">Unable to verify? You can upload current documents or ask your trip organiser for help.</p></div>
    </section>
  </div></main>;
}

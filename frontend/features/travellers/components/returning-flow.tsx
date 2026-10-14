"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowLeft, LockKeyhole } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import { UploadHeader } from "@/features/upload/components/upload-flow-shell";
import { TravellerShell } from "@/features/upload/components/traveller-shell";
import { useReturningClaim } from "../hooks/use-returning-claim";
import type { CompletionResult, ReplacementRequest, ReturningCapabilities, ReturningMethod, ReturningOwnedSource } from "../types";
import { PassportProofFields } from "./returning-fields";
import { ReturningChallenge } from "./returning-challenge";
import { ReturningPhone } from "./returning-phone";
import { ReturningReview } from "./returning-review";

type Props = {
  token: string; group: UploadLinkResponse; initialMethod: ReturningMethod;
  capabilities: ReturningCapabilities; onFresh: () => void; onBack?: () => void;
  onReplace: (request: ReplacementRequest) => void; ownedSource?: ReturningOwnedSource;
  onCompleted?: (result: CompletionResult) => void;
};
const HEADINGS: Record<string, string> = {
  phone: "Verify your WhatsApp", passport: "Find your saved passport", code: "Enter your individual code",
  identify: "Choose the traveller", challenge: "One more check", confirm: "Opening your passport", recovery: "Opening your passport", review: "Opening your passport",
};

export function ReturningFlow({ token, group, initialMethod, capabilities, onFresh, onBack, onReplace, ownedSource, onCompleted }: Props) {
  const claim = useReturningClaim();
  const [passport, setPassport] = useState("");
  const [code, setCode] = useState("");
  const freshButton = useRef<HTMLButtonElement>(null);
  const stage = claim.transition?.stage;
  const failedProof = Boolean(claim.error && (stage === "challenge" || stage === "passport"));
  useEffect(() => { if (failedProof) freshButton.current?.focus({ preventScroll: true }); }, [failedProof]);
  if (stage === "review" && claim.history) return <ReturningReview history={claim.history} groupName={group.name} group={group} groupToken={token} onFresh={onFresh} onReplace={onReplace} ownedSource={ownedSource} onCompleted={onCompleted} />;
  const isPhone = initialMethod === "phone" && (!stage || stage === "contact");
  const headingKey = isPhone ? "phone" : stage || initialMethod;
  return <TravellerShell>
    <UploadHeader groupName={group.name} departureDate={group.travel_date} returnDate={group.return_date} />
    {onBack && <button type="button" disabled={claim.pending} onClick={onBack} className="mb-3 inline-flex min-h-11 items-center gap-2 text-sm font-medium text-slate-600 hover:text-blue-700"><ArrowLeft className="h-4 w-4" />Other verification options</button>}
    <section className="space-y-6 rounded-3xl border border-slate-200/80 bg-white p-5 shadow-[0_16px_50px_-30px_rgba(15,45,90,0.3)] sm:p-8" aria-busy={claim.pending}>
      <header>
        <span className="mb-4 flex h-11 w-11 items-center justify-center rounded-2xl bg-blue-50 text-blue-600"><LockKeyhole className="h-5 w-5" aria-hidden="true" /></span>
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-600">Returning traveller</p>
        <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">{HEADINGS[headingKey]}</h2>
        <p className="mt-2 text-sm leading-6 text-slate-500">{stage === "challenge" ? "Enter the date exactly as printed on your passport. We’ll check it with your passport number before opening your saved details." : "A quick verification keeps your saved travel documents private."}</p>
      </header>
      {claim.error && <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm leading-6 text-red-800">{failedProof ? "We couldn’t verify a saved record with these details. Check your entries, try another verification option, or continue as a new traveller." : claim.error}</div>}
      {isPhone && <ReturningPhone started={stage === "contact"} pending={claim.pending} otpSent={claim.otpSent} resendAt={claim.resendAt} onStart={(phone) => void claim.start({ group_token: token, method: "phone", phone_number: phone })} onResend={() => void claim.requestOtp()} onVerify={(otp) => void claim.verifyOtp(otp)} />}
      {!stage && initialMethod !== "phone" && <form className="space-y-5" onSubmit={(event) => {
        event.preventDefault();
        void claim.start({ group_token: token, method: initialMethod, ...(initialMethod === "passport" ? { passport_number: passport } : { individual_code: code }) });
      }}>
        {initialMethod === "passport" ? <PassportProofFields number={passport} onNumber={setPassport} disabled={claim.pending} /> : <Input label={capabilities.code_label ?? "Agent / employee code"} value={code} onChange={(event) => setCode(event.target.value)} maxLength={128} required autoComplete="off" disabled={claim.pending} hint="Use your individual code, including any leading zeros." className="h-12 text-base" />}
        <Button type="submit" className="min-h-12 w-full" isLoading={claim.pending}>Continue</Button>
      </form>}
      {stage === "identify" && claim.candidates && <div className="space-y-3"><p className="text-sm leading-6 text-slate-600">Select your record, then confirm the full passport number.</p><ul className="space-y-2">{claim.candidates.items.map((person) => <li key={person.handle}><Button type="button" variant="secondary" className="h-auto min-h-12 w-full justify-between whitespace-normal py-3 text-left" disabled={claim.pending} onClick={() => void claim.select(person.handle)}><span>{person.label}</span><span className="text-xs text-slate-500">{person.passport_hint}</span></Button></li>)}</ul></div>}
      {stage === "passport" && <form className="space-y-5" onSubmit={(event) => { event.preventDefault(); void claim.passport({ passport_number: passport }); }}><PassportProofFields number={passport} onNumber={setPassport} disabled={claim.pending} /><Button type="submit" isLoading={claim.pending} className="min-h-12 w-full">Verify passport</Button></form>}
      {stage === "challenge" && claim.transition && <ReturningChallenge transition={claim.transition} pending={claim.pending} onVerify={(answers) => void claim.challenge(answers)} onChangeQuestion={(field) => void claim.changeQuestion(field)} />}
      {((stage === "identify" && !claim.candidates) || stage === "confirm" || stage === "recovery" || stage === "review") && <Button type="button" className="min-h-12 w-full" isLoading={claim.pending} onClick={() => void claim.retryStage()}>Load verified details</Button>}
      <div className="border-t border-slate-100 pt-5"><Button ref={freshButton} type="button" variant={failedProof ? "secondary" : "ghost"} className={`h-auto min-h-12 w-full whitespace-normal ${failedProof ? "border-blue-400 bg-blue-50 text-blue-700 ring-2 ring-blue-100" : ""}`} onClick={onFresh} disabled={claim.pending}>Continue as a new traveller</Button></div>
    </section>
  </TravellerShell>;
}

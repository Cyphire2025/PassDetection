"use client";
import { CheckCircle2, Mail, Phone } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { FreshDraftState } from "../hooks/use-fresh-draft";
import { useFreshContact, type FreshProof } from "../hooks/use-fresh-contact";
import { ContactInput } from "./upload-flow-fields";
import { validContactEmail } from "./upload-contact-verification";

export type { FreshProof } from "../hooks/use-fresh-contact";
export function FreshContact({ state, onProof }: { state: FreshDraftState; onProof: (proof: FreshProof | null) => void }) {
  const { email, phone, normalized, valid, code, setCode, now, challenge, resend, request, verify } = useFreshContact(state, onProof);
  return <section className="mt-6 border-t border-slate-100 pt-5" aria-label="Contact verification">
    <h3 className="mb-4 font-semibold text-slate-900">Contact details</h3>
    <div className="grid gap-4 sm:grid-cols-2"><ContactInput label="Email" type="email" icon={<Mail className="h-4 w-4" />} value={email} required onChange={(value) => state.update("current_details", "client_email", value)} /><ContactInput label="WhatsApp number" type="tel" icon={<Phone className="h-4 w-4" />} value={phone} required onChange={(value) => state.update("current_details", "client_phone", value)} /></div>
    {email.trim() && !validContactEmail(email) && <p role="alert" className="mt-2 text-sm text-red-700">Enter a valid email address, such as name@example.com.</p>}
    {(!email.trim() || !phone.trim()) && <p className="mt-2 text-xs leading-5 text-slate-500">Enter your email and WhatsApp number to receive a verification code.</p>}
    {valid ? <p role="status" className="mt-3 flex items-center gap-2 text-sm text-emerald-700"><CheckCircle2 className="h-4 w-4" />WhatsApp number verified</p> : <div className="mt-4 space-y-3">
      <Button type="button" variant="secondary" disabled={state.pending || !normalized || !validContactEmail(email) || resend > 0} onClick={request}>{resend > 0 ? `Resend in ${resend}s` : challenge ? "Resend code" : "Verify WhatsApp number"}</Button>
      {challenge && <div className="space-y-2"><label className="block text-sm font-medium text-slate-700">Verification code<Input value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))} inputMode="numeric" autoComplete="one-time-code" maxLength={6} className="mt-2 h-12" /></label><Button type="button" disabled={state.pending || code.length !== 6 || challenge.expiresAt <= now} onClick={verify}>Confirm code</Button>{challenge.expiresAt <= now && <p role="alert" className="text-sm text-red-700">This code expired. Request a new code.</p>}</div>}
    </div>}
  </section>;
}

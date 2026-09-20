"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Mail, Phone, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { normalizePhoneNumber } from "@/lib/utils/phone-number";
import { uploadApi } from "../api/upload.api";
import { normalizeOtpPhone } from "../services/contact-verification";
import { errorMessage } from "../services/upload-flow-helpers";
import { ContactInput } from "./upload-flow-fields";
import { BackButton, ErrorMessage } from "./upload-flow-shell";

export interface ContactVerification {
  id: string;
  phone: string;
  email: string;
  sessionId: string;
  expiresAt: number;
}

export function validContactEmail(email: string) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()) && email.trim().length <= 254;
}

interface Props {
  token: string;
  submissionId: string;
  sessionId: string;
  name: string;
  progress?: string;
  email: string;
  phone: string;
  verification: ContactVerification | null;
  onContactChange: (email: string, phone: string) => void;
  onVerified: (verification: ContactVerification) => void;
  onBack: () => void;
}

export function UploadContactVerification({ token, submissionId, sessionId, name, progress, email, phone, verification, onContactChange, onVerified, onBack }: Props) {
  const [challenge, setChallenge] = useState<{ id: string; phone: string; email: string; expiresAt: number } | null>(null);
  const [resendAt, setResendAt] = useState(0);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState<"send" | "verify" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const operationRef = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);
  const inFlightRef = useRef(false);
  const otpInputRef = useRef<HTMLInputElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const inputId = useId();
  const normalizedPhone = normalizeOtpPhone(phone);
  const emailValid = validContactEmail(email);
  const secondsUntilResend = Math.max(0, Math.ceil((resendAt - now) / 1000));
  const expired = Boolean(challenge && challenge.expiresAt <= now);

  useEffect(() => {
    titleRef.current?.focus();
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => {
      window.clearInterval(timer);
      operationRef.current += 1;
      controllerRef.current?.abort();
    };
  }, []);

  useEffect(() => { if (challenge) otpInputRef.current?.focus(); }, [challenge]);

  const changeContact = (nextEmail: string, nextPhone: string) => {
    operationRef.current += 1;
    controllerRef.current?.abort();
    inFlightRef.current = false;
    setBusy(null);
    setChallenge(null);
    setCode("");
    setError(null);
    onContactChange(nextEmail, nextPhone);
  };

  const requestCode = async () => {
    if (inFlightRef.current || !normalizedPhone || !emailValid || Date.now() < resendAt) return;
    const operation = ++operationRef.current;
    const controller = new AbortController();
    controllerRef.current = controller;
    inFlightRef.current = true;
    setBusy("send");
    setError(null);
    try {
      const result = await uploadApi.requestContactOtp(submissionId, sessionId, {
        group_token: token, phone_number: normalizedPhone, email: email.trim(),
      }, controller.signal);
      if (operation !== operationRef.current) return;
      const receivedAt = Date.now();
      setNow(receivedAt);
      setChallenge({ id: result.challenge_id, phone: normalizedPhone, email: email.trim(), expiresAt: receivedAt + result.expires_in_seconds * 1000 });
      setResendAt(receivedAt + result.resend_after_seconds * 1000);
      setCode("");
    } catch (cause) {
      if (operation === operationRef.current) {
        setError(errorMessage(cause, "We could not send your WhatsApp code. Please try again."));
        const retryAfterMs = cause && typeof cause === "object" && "retryAfterMs" in cause ? cause.retryAfterMs : undefined;
        if (typeof retryAfterMs === "number" && retryAfterMs > 0) { setNow(Date.now()); setResendAt(Date.now() + retryAfterMs); }
      }
    } finally {
      if (operation === operationRef.current) { inFlightRef.current = false; setBusy(null); }
    }
  };

  const verifyCode = async (event: React.FormEvent) => {
    event.preventDefault();
    if (inFlightRef.current || !challenge || challenge.expiresAt <= Date.now() || !/^\d{6}$/.test(code)) return;
    const operation = ++operationRef.current;
    const controller = new AbortController();
    controllerRef.current = controller;
    inFlightRef.current = true;
    setBusy("verify");
    setError(null);
    try {
      const result = await uploadApi.verifyContactOtp(submissionId, sessionId, {
        group_token: token, challenge_id: challenge.id, code,
      }, controller.signal);
      if (operation !== operationRef.current) return;
      if (normalizePhoneNumber(result.phone_number) !== challenge.phone) throw new Error("The verified number has changed. Please request a new code.");
      onVerified({ id: result.phone_verification_id, phone: challenge.phone, email: challenge.email, sessionId, expiresAt: Date.now() + result.expires_in_seconds * 1000 });
    } catch (cause) {
      if (operation === operationRef.current) setError(errorMessage(cause, "The code could not be verified. Check the code and try again."));
    } finally {
      if (operation === operationRef.current) { inFlightRef.current = false; setBusy(null); }
    }
  };

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-6 sm:py-12" data-testid="contact-verification-page">
      <div className="mx-auto max-w-lg">
        <BackButton onClick={onBack} />
        <section className="mt-4 rounded-3xl border border-slate-100 bg-white p-5 shadow-xl shadow-slate-200/50 sm:p-7">
          <ShieldCheck className="mb-4 h-9 w-9 text-blue-600" aria-hidden="true" />
          {progress && <p className="mb-2 text-sm font-semibold text-blue-700">{progress}</p>}
          <h1 ref={titleRef} tabIndex={-1} className="text-2xl font-bold tracking-tight text-slate-900 outline-none">Verify your WhatsApp number</h1>
          <p className="mt-2 text-sm leading-6 text-slate-600">{name ? `${name}, enter` : "Enter"} your email and active WhatsApp number. Verify the code to continue to your details on the next page.</p>
          <form onSubmit={verifyCode} className="mt-6 space-y-5">
            <ContactInput icon={<Mail className="h-5 w-5" />} label="Email" type="email" value={email} onChange={(value) => changeContact(value, phone)} required maxLength={254} />
            <ContactInput icon={<Phone className="h-5 w-5" />} label="WhatsApp active number" type="tel" value={phone} onChange={(value) => changeContact(email, value)} phoneNormalizer={normalizeOtpPhone} required />
            <p className="rounded-xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm leading-6 text-blue-900">
              All further trip details, travel documents and important updates will be shared on this WhatsApp number. Please use a number you check regularly.
            </p>
            <ErrorMessage message={error} />
            {verification ? (
              <>
                <p role="status" className="text-sm font-medium text-emerald-700">WhatsApp number verified. Changing your email or number requires a new code.</p>
                <Button type="button" className="h-12 w-full" onClick={() => onVerified(verification)}>Continue to your details</Button>
              </>
            ) : (
              <>
                {normalizedPhone && <Button type="button" variant={challenge ? "secondary" : "primary"} className="h-12 w-full" onClick={() => void requestCode()} disabled={!emailValid || busy !== null || secondsUntilResend > 0}>
                  {busy === "send" ? "Sending OTP…" : secondsUntilResend > 0 ? `Resend OTP in ${secondsUntilResend}s` : challenge ? "Resend OTP" : "Send OTP"}
                </Button>}
                {normalizedPhone && !emailValid && <p className="text-xs text-slate-500">Enter a valid email address to send your code.</p>}
                {challenge && (
                  <div className="space-y-4 border-t border-slate-100 pt-5">
                    <p role="status" className={`text-sm leading-6 ${expired ? "text-amber-800" : "text-slate-600"}`}>
                      {expired ? "This code has expired. Request a new OTP to continue." : `A 6-digit code was sent to ${challenge.phone} on WhatsApp. Use the latest code.`}
                    </p>
                    <label htmlFor={inputId} className="block text-sm font-semibold text-slate-700">WhatsApp verification code</label>
                    <Input ref={otpInputRef} id={inputId} value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))} inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required disabled={expired || busy === "verify"} className="h-12 text-center text-xl tracking-[0.35em]" />
                    <Button type="submit" className="h-12 w-full" disabled={busy !== null || expired || !/^\d{6}$/.test(code)}>{busy === "verify" ? "Verifying…" : "Verify OTP and continue"}</Button>
                  </div>
                )}
              </>
            )}
          </form>
        </section>
      </div>
    </main>
  );
}

export function VerifiedContactSummary({ email, phone, onEdit }: { email: string; phone: string; onEdit: () => void }) {
  return <div className="my-5 rounded-xl border border-emerald-100 bg-emerald-50 p-4">
    <p className="text-sm font-semibold text-emerald-800">WhatsApp verified: {normalizePhoneNumber(phone)}</p>
    <p className="mt-1 break-all text-sm text-slate-600">{email}</p>
    <button type="button" onClick={onEdit} className="mt-2 text-sm font-semibold text-blue-700 underline underline-offset-4">Change contact details</button>
  </div>;
}

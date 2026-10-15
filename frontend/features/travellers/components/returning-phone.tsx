"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { normalizePhoneNumber, PHONE_FORMAT_HELP } from "@/lib/utils/phone-number";

export function ReturningPhone({ started, pending, otpSent, resendAt, onStart, onResend, onVerify }: {
  started: boolean; pending: boolean; otpSent: boolean; resendAt: number;
  onStart: (phone: string) => void; onResend: () => void; onVerify: (code: string) => void;
}) {
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!resendAt) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [resendAt]);
  const remaining = Math.max(0, Math.ceil((resendAt - now) / 1000));
  return <div className="space-y-6">
    <form onSubmit={(event) => { event.preventDefault(); if (started) onResend(); else onStart(normalizePhoneNumber(phone) ?? phone); }}>
      <div className="flex items-end gap-2">
        <div className="min-w-0 flex-1"><Input label="WhatsApp number" type="tel" autoComplete="tel" value={phone} onChange={(event) => setPhone(event.target.value)} required maxLength={64} disabled={pending || started} className="h-12 text-base" /></div>
        <Button type="submit" variant="secondary" className="h-12 shrink-0 px-3" disabled={pending || (!started && !normalizePhoneNumber(phone)) || (otpSent && remaining > 0)}>
          {otpSent ? remaining > 0 ? `${remaining}s` : "Resend OTP" : "Send OTP"}
        </Button>
      </div>
      <p className="mt-2 text-xs leading-5 text-slate-500">{PHONE_FORMAT_HELP}</p>
    </form>
    <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); onVerify(code); }}>
      <Input label="Enter verification code" value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))} required inputMode="numeric" autoComplete="one-time-code" minLength={6} maxLength={6} disabled={pending || !otpSent} hint={otpSent ? "Enter the six-digit code sent to your WhatsApp." : "Your code will arrive after you select Send OTP."} className="h-12 text-base tracking-[0.3em]" />
      <Button type="submit" isLoading={pending} disabled={!otpSent || code.length !== 6} className="min-h-12 w-full">Verify WhatsApp</Button>
    </form>
  </div>;
}

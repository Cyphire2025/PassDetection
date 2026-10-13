"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { normalizePhoneNumber, PHONE_FORMAT_HELP } from "@/lib/utils/phone-number";
import { returningApi } from "../api/returning.api";
import type { ReturningHistory } from "../types";

export function ReturningContactDialog({ onClose, onSaved }: { onClose: () => void; onSaved: (history: ReturningHistory) => void }) {
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [verified, setVerified] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();
  const [resendAt, setResendAt] = useState(0);
  const [now, setNow] = useState(0);
  const operation = useRef<AbortController | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const keyboard = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: !pending, onClose });
  useEffect(() => () => operation.current?.abort(), []);
  useEffect(() => { if (!resendAt) return; const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, [resendAt]);
  const run = async (verify: boolean) => {
    if (operation.current) return;
    const controller = new AbortController(); operation.current = controller; setPending(true); setError(undefined);
    try {
      if (verify) {
        if (!verified) {
          await returningApi.verifyContact(code, controller.signal);
          if (!controller.signal.aborted) setVerified(true);
        }
        const history = await returningApi.history(controller.signal);
        if (!controller.signal.aborted) onSaved(history);
      } else {
        const result = await returningApi.requestContact(normalizePhoneNumber(phone) ?? phone, controller.signal);
        if (!controller.signal.aborted) { setSent(true); setNow(Date.now()); setResendAt(Date.now() + result.resend_after_seconds * 1000); }
      }
    } catch (cause) { if (!controller.signal.aborted) setError(typeof cause === "object" && cause !== null && "message" in cause && typeof cause.message === "string" ? cause.message : "The contact change could not be confirmed. Retry when ready."); }
    finally { operation.current = null; if (!controller.signal.aborted) setPending(false); }
  };
  const resendIn = Math.max(0, Math.ceil((resendAt - now) / 1000));
  return <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} onKeyDown={keyboard} className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
    <form className="max-h-[90dvh] w-full max-w-md space-y-4 overflow-y-auto rounded-2xl bg-white p-5 shadow-xl" onSubmit={(event) => { event.preventDefault(); if (!sent || confirmed) void run(sent); }}>
      <h2 id={titleId} className="text-lg font-semibold text-slate-950">Change WhatsApp contact</h2>
      <p className="text-sm leading-6 text-slate-600">Verify the new number before it becomes this traveller’s contact for future trips. Other people sharing the old or new number remain unchanged.</p>
      <Input label="New WhatsApp number" value={phone} type="tel" autoComplete="tel" maxLength={64} required onChange={(event) => setPhone(event.target.value)} disabled={pending || sent} hint={PHONE_FORMAT_HELP} data-dialog-initial-focus className="h-12 text-base" />
      {sent && <><Input label="WhatsApp verification code" value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))} inputMode="numeric" autoComplete="one-time-code" required minLength={6} maxLength={6} disabled={pending} className="h-12 text-base" /><Button type="button" variant="ghost" size="sm" disabled={pending || verified || resendIn > 0} onClick={() => void run(false)}>{resendIn ? `Resend available in ${resendIn}s` : "Resend code"}</Button><label className="flex items-start gap-3 text-sm leading-6 text-slate-700"><input type="checkbox" required checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} className="mt-1" />Use this verified number as this traveller’s current contact.</label></>}
      {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      <div className="flex flex-wrap justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose} disabled={pending}>Cancel</Button><Button type="submit" disabled={!normalizePhoneNumber(phone) || (sent && (!confirmed || code.length !== 6))} isLoading={pending}>{verified ? "Refresh verified contact" : sent ? "Verify and update contact" : "Send WhatsApp code"}</Button></div>
    </form>
  </div>;
}

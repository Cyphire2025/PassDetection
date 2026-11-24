"use client";
import { useId, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { normalizePhoneNumber, PHONE_FORMAT_HELP } from "@/lib/utils/phone-number";
import { useReturningContact } from "../hooks/use-returning-contact";

export function ReturningContactDialog({ draftId, onClose, onSaved }: { draftId: string; onClose: () => void; onSaved: () => void }) {
  const {
    phone,
    setPhone,
    code,
    setCode,
    sent,
    verified,
    confirmed,
    setConfirmed,
    pending,
    error,
    resendIn,
    run
  } = useReturningContact(draftId, onSaved);
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const keyboard = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: !pending, onClose });
  return <div
    ref={dialogRef}
    role="dialog"
    aria-modal="true"
    aria-labelledby={titleId}
    onKeyDown={keyboard}
    className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
  >
    <form
      className="max-h-[90dvh] w-full max-w-md space-y-4 overflow-y-auto rounded-2xl bg-white p-5 shadow-xl"
      onSubmit={(event) => {
        event.preventDefault();
        if (!sent || confirmed) void run(sent);
      }}
    >
      <h2 id={titleId} className="text-lg font-semibold text-slate-950">Change WhatsApp contact</h2>
      <p className="text-sm leading-6 text-slate-600">Verify your current WhatsApp number. It will be saved with your trip only when you select Submit on the review page.</p>
      <Input
        label="New WhatsApp number"
        value={phone}
        type="tel"
        autoComplete="tel"
        maxLength={64}
        required
        onChange={(event) => setPhone(event.target.value)}
        disabled={pending || sent}
        hint={PHONE_FORMAT_HELP}
        data-dialog-initial-focus
        className="h-12 text-base"
      />
      {sent && <>
        <Input
          label="WhatsApp verification code"
          value={code}
          onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
          inputMode="numeric"
          autoComplete="one-time-code"
          required
          minLength={6}
          maxLength={6}
          disabled={pending}
          className="h-12 text-base"
        />
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={pending || verified || resendIn > 0}
          onClick={() => void run(false)}
        >
          {resendIn ? `Resend available in ${resendIn}s` : "Resend code"}
        </Button>
        <label className="flex items-start gap-3 text-sm leading-6 text-slate-700">
          <input
            type="checkbox"
            required
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
            className="mt-1"
          />Use this verified number as this traveller’s current contact.</label>
      </>}
      {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-800">
        {error}
      </p>}
      <div className="flex flex-wrap justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onClose} disabled={pending}>Cancel</Button>
        <Button
          type="submit"
          disabled={!normalizePhoneNumber(phone) || (sent && (!confirmed || code.length !== 6))}
          isLoading={pending}
        >
          {verified ? "Use verified contact" : sent ? "Verify for this draft" : "Send WhatsApp code"}
        </Button>
      </div>
    </form>
  </div>;
}

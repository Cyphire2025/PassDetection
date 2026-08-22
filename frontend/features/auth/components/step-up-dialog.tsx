"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { ShieldCheck, X } from "lucide-react";
import { Button, Input } from "@/components/ui";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { authApi } from "../api/auth.api";
import {
  cancelAuthenticationStepUp,
  completeAuthenticationStepUp,
  STEP_UP_REQUIRED_EVENT,
} from "../services/step-up-coordinator";

export function StepUpDialog() {
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const show = () => {
      setCode("");
      setError(null);
      setOpen(true);
    };
    window.addEventListener(STEP_UP_REQUIRED_EVENT, show);
    return () => window.removeEventListener(STEP_UP_REQUIRED_EVENT, show);
  }, []);

  const close = useCallback(() => {
    if (isSubmitting) return;
    setOpen(false);
    cancelAuthenticationStepUp();
  }, [isSubmitting]);
  const handleDialogKeyDown = useModalKeyboardBoundary({
    dialogRef,
    isOpen: open,
    canClose: !isSubmitting,
    onClose: close,
  });

  if (!open) return null;
  const verify = async () => {
    setError(null);
    setIsSubmitting(true);
    try {
      await authApi.stepUp(code.trim());
      setOpen(false);
      completeAuthenticationStepUp();
    } catch {
      setError("The authenticator or recovery code was rejected. Try a fresh code.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-sm" role="presentation">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        onKeyDown={handleDialogKeyDown}
        className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-700"><ShieldCheck className="h-5 w-5" aria-hidden="true" /></span>
            <div>
              <h2 id={titleId} className="font-semibold text-slate-950">Confirm this sensitive action</h2>
              <p id={descriptionId} className="mt-1 text-sm leading-5 text-slate-600">Enter a current authenticator code or one unused recovery code. The original action will retry once after verification.</p>
            </div>
          </div>
          <button type="button" onClick={close} disabled={isSubmitting} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label="Cancel identity confirmation"><X className="h-5 w-5" /></button>
        </div>
        <div className="mt-5 space-y-4">
          <Input label="Verification code" autoComplete="one-time-code" value={code} onChange={(event) => setCode(event.target.value)} data-dialog-initial-focus />
          {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" disabled={isSubmitting} onClick={close}>Cancel</Button>
            <Button type="button" isLoading={isSubmitting} disabled={code.trim().length < 6} onClick={() => void verify()}>Verify and continue</Button>
          </div>
        </div>
      </div>
    </div>
  );
}

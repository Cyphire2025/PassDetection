"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { UncertainWhatsAppSendError } from "../utils/normal-send-storage";
import { readErrorMessage } from "./whatsapp-dialog-ui";

export function useNormalSendRecovery(setError: (message: string | null) => void) {
  const [recovery, setRecovery] = useState<UncertainWhatsAppSendError | null>(null);
  const capture = (cause: unknown) => setRecovery(cause instanceof UncertainWhatsAppSendError ? cause : null);
  const startNew = () => {
    try {
      recovery?.startNew();
      setRecovery(null);
      setError(null);
    } catch (cause) {
      setError(readErrorMessage(cause, "The earlier request could not be retained safely."));
    }
  };
  const notice = recovery ? (
    <div role="alert" className="space-y-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
      <p>The earlier send may already be queued or delivered. Starting another send does not cancel it and may deliver another message.</p>
      <Button type="button" variant="secondary" className="h-auto whitespace-normal text-left" onClick={startNew}>
        I checked delivery history — start a separate send
      </Button>
      <p className="text-xs">This choice only clears the retry warning. Review this draft and press Send to submit it.</p>
    </div>
  ) : null;
  return { capture, notice };
}

import { useEffect, useRef, useState } from "react";
import { normalizePhoneNumber } from "@/lib/utils/phone-number";
import { returningApi } from "../api/returning.api";

export function useReturningContact(draftId: string, onSaved: () => void) {
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
  useEffect(() => () => operation.current?.abort(), []);
  useEffect(() => {
    if (!resendAt) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [resendAt]);
  const run = async (verify: boolean) => {
    if (operation.current) return;
    const controller = new AbortController();
    operation.current = controller;
    setPending(true);
    setError(undefined);
    try {
      if (verify) {
        if (!verified) {
          await returningApi.verifyContact(code, draftId, controller.signal);
          if (!controller.signal.aborted) setVerified(true);
        }
        if (!controller.signal.aborted) onSaved();
      } else {
        const result = await returningApi.requestContact(normalizePhoneNumber(phone) ?? phone, draftId, controller.signal);
        if (!controller.signal.aborted) {
          setSent(true);
          setNow(Date.now());
          setResendAt(Date.now() + result.resend_after_seconds * 1000);
        }
      }
    } catch (cause) {
      if (!controller.signal.aborted) setError(typeof cause === "object" && cause !== null && "message" in cause && typeof cause.message === "string" ? cause.message : "The contact change could not be confirmed. Retry when ready.");
    }
    finally {
      operation.current = null;
      if (!controller.signal.aborted) setPending(false);
    }
  };
  const resendIn = Math.max(0, Math.ceil((resendAt - now) / 1000));
  return { phone, setPhone, code, setCode, sent, verified, confirmed, setConfirmed, pending, error, resendIn, run };
}

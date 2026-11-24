import { useEffect, useState } from "react";
import { returningApi } from "../api/returning.api";
import type { ReturningHistory } from "../types";

export function useReturningResume(token: string) {
  const [history, setHistory] = useState<ReturningHistory>();
  const [verificationNeeded, setVerificationNeeded] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void returningApi.history(controller.signal, token).then((result) => {
      if (!controller.signal.aborted) setHistory(result);
    })
      .catch(() => {
        if (!controller.signal.aborted) setVerificationNeeded(true);
      });
    return () => controller.abort();
  }, [token]);
  return { history, verificationNeeded };
}

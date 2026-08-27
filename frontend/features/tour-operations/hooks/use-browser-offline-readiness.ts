"use client";

import { useEffect, useMemo, useState } from "react";

import {
  BROWSER_OFFLINE_READINESS_RECHECK_MS,
  browserOfflineReadinessRecheckDelay,
  resolveBrowserOfflineReadiness,
  type BrowserOfflineReadinessState,
} from "../services/browser-offline-readiness";

export function useBrowserOfflineReadiness({
  enabled,
  groupId,
  isOnline,
  refreshWhenOnline,
  sessionId,
}: Readonly<{
  enabled: boolean;
  groupId: string;
  isOnline: boolean;
  refreshWhenOnline: boolean;
  sessionId: string | null;
}>): BrowserOfflineReadinessState {
  const scopeKey = useMemo(
    () => JSON.stringify([groupId, sessionId]),
    [groupId, sessionId],
  );
  const [result, setResult] = useState<Readonly<{
    scopeKey: string;
    state: Exclude<BrowserOfflineReadinessState, { status: "checking" }>;
  }> | null>(null);

  useEffect(() => {
    if (!enabled) return;

    const controller = new AbortController();
    let currentState: Exclude<BrowserOfflineReadinessState, { status: "checking" }> | null = null;
    let inFlight: Promise<void> | null = null;
    let requestedRefresh = false;
    let retryTimer: number | null = null;

    const evaluate = (refreshOnline: boolean): Promise<void> => {
      requestedRefresh ||= refreshOnline;
      if (inFlight !== null) return inFlight;

      inFlight = (async () => {
        do {
          const shouldRefresh = requestedRefresh;
          requestedRefresh = false;
          if (retryTimer !== null) {
            window.clearTimeout(retryTimer);
            retryTimer = null;
          }
          const next = await resolveBrowserOfflineReadiness({
            groupId,
            refreshOnline: shouldRefresh,
            sessionId,
            signal: controller.signal,
          }).catch(() => null);
          if (next === null || controller.signal.aborted) return;

          currentState = next;
          setResult({ scopeKey, state: next });
          if (
            next.status === "unavailable"
            && !shouldRefresh
            && isOnline
            && refreshWhenOnline
          ) {
            requestedRefresh = true;
          }
        } while (requestedRefresh && !controller.signal.aborted);

        if (currentState === null || controller.signal.aborted) return;
        const delay = currentState.status === "ready"
          ? browserOfflineReadinessRecheckDelay(currentState)
          : BROWSER_OFFLINE_READINESS_RECHECK_MS;
        retryTimer = window.setTimeout(() => {
          void evaluate(
            currentState?.status === "unavailable" && isOnline && refreshWhenOnline,
          );
        }, delay);
      })().finally(() => {
        inFlight = null;
      });
      return inFlight;
    };

    const handleVisibility = () => {
      if (document.visibilityState !== "visible") return;
      void evaluate(
        currentState?.status === "unavailable" && isOnline && refreshWhenOnline,
      );
    };

    void evaluate(isOnline && refreshWhenOnline);
    document.addEventListener("visibilitychange", handleVisibility);
    window.addEventListener("pageshow", handleVisibility);
    return () => {
      controller.abort();
      if (retryTimer !== null) window.clearTimeout(retryTimer);
      document.removeEventListener("visibilitychange", handleVisibility);
      window.removeEventListener("pageshow", handleVisibility);
    };
  }, [enabled, groupId, isOnline, refreshWhenOnline, scopeKey, sessionId]);

  if (enabled && result?.scopeKey === scopeKey) return result.state;
  return { groupId, sessionId, status: "checking" };
}

"use client";

import type { QueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { SENSITIVE_STATE_RESET_EVENT } from "@/features/auth/services/session-state";

type RecoveryState = "online" | "offline" | "recovering" | "error";

const RECOVERY_THROTTLE_MS = 1_500;
const OFFLINE_RECHECK_MS = 2_000;
const WAKE_GAP_MS = 60_000;
const HEARTBEAT_MS = 30_000;

export function SessionLifecycle({ queryClient }: { queryClient: QueryClient }) {
  const [state, setState] = useState<RecoveryState>(() =>
    typeof navigator !== "undefined" && !navigator.onLine ? "offline" : "online",
  );
  const mountedRef = useRef(false);
  const recoveryRef = useRef<Promise<void> | null>(null);
  const recoveryGenerationRef = useRef(0);
  const lastRecoveryAtRef = useRef(0);
  const lastHeartbeatRef = useRef(0);

  const recover = useCallback((force = false) => {
    if (!navigator.onLine) {
      if (mountedRef.current) setState("offline");
      return Promise.resolve();
    }
    if (document.visibilityState === "hidden") return Promise.resolve();
    if (recoveryRef.current) return recoveryRef.current;
    if (!force && Date.now() - lastRecoveryAtRef.current < RECOVERY_THROTTLE_MS) {
      return Promise.resolve();
    }

    const generation = ++recoveryGenerationRef.current;
    lastRecoveryAtRef.current = Date.now();
    if (mountedRef.current) setState("recovering");

    const recovery = (async () => {
      await queryClient.resumePausedMutations();
      await queryClient.refetchQueries(
        { type: "active", stale: true },
        { cancelRefetch: true, throwOnError: true },
      );
    })()
      .then(() => {
        if (mountedRef.current && recoveryGenerationRef.current === generation) {
          setState("online");
        }
      })
      .catch(() => {
        if (mountedRef.current && recoveryGenerationRef.current === generation) {
          setState(navigator.onLine ? "error" : "offline");
        }
      })
      .finally(() => {
        if (recoveryRef.current === recovery) recoveryRef.current = null;
      });

    recoveryRef.current = recovery;
    return recovery;
  }, [queryClient]);

  useEffect(() => {
    mountedRef.current = true;
    lastHeartbeatRef.current = Date.now();

    const handleOnline = () => {
      void recover(true);
    };
    const handleOffline = () => {
      recoveryGenerationRef.current += 1;
      setState("offline");
    };
    const handleUsable = () => {
      if (document.visibilityState === "visible" && navigator.onLine) {
        void recover();
      }
    };
    const handleVisibility = () => {
      if (document.visibilityState === "visible") handleUsable();
    };
    const handleSensitiveStateReset = () => {
      recoveryGenerationRef.current += 1;
      void queryClient.cancelQueries();
      queryClient.clear();
    };
    const heartbeat = window.setInterval(() => {
      const now = Date.now();
      const likelyWokeFromSleep = now - lastHeartbeatRef.current > WAKE_GAP_MS;
      lastHeartbeatRef.current = now;
      if (likelyWokeFromSleep) handleUsable();
    }, HEARTBEAT_MS);

    window.addEventListener("focus", handleUsable);
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    window.addEventListener("pageshow", handleUsable);
    window.addEventListener(SENSITIVE_STATE_RESET_EVENT, handleSensitiveStateReset);
    document.addEventListener("visibilitychange", handleVisibility);
    // Reconcile immediately in case the browser came back online before the
    // event listeners were attached. Otherwise the initial offline state can
    // remain stuck until another focus, visibility, or online event occurs.
    handleUsable();

    return () => {
      mountedRef.current = false;
      recoveryGenerationRef.current += 1;
      window.clearInterval(heartbeat);
      window.removeEventListener("focus", handleUsable);
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
      window.removeEventListener("pageshow", handleUsable);
      window.removeEventListener(SENSITIVE_STATE_RESET_EVENT, handleSensitiveStateReset);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [queryClient, recover]);

  useEffect(() => {
    if (state !== "offline") return;

    const reconcile = window.setInterval(() => {
      if (navigator.onLine) void recover(true);
    }, OFFLINE_RECHECK_MS);

    return () => window.clearInterval(reconcile);
  }, [recover, state]);

  return null;
}

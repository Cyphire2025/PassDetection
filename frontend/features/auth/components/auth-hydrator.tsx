"use client";

import { useCallback, useEffect, useRef } from "react";
import { authApi } from "../api/auth.api";
import { subscribeToSessionResets } from "../services/session-state";
import { useAuthStore } from "@/stores/auth.store";

const SESSION_RECHECK_INTERVAL_MS = 60_000;
const WAKE_CHECK_INTERVAL_MS = 30_000;

export function AuthHydrator() {
  const setSession = useAuthStore((state) => state.setSession);
  const clearSession = useAuthStore((state) => state.clearSession);
  const markHydrated = useAuthStore((state) => state.markHydrated);
  const mountedRef = useRef(false);
  const activeControllerRef = useRef<AbortController | null>(null);
  const verificationRef = useRef<Promise<void> | null>(null);
  const lastVerifiedAtRef = useRef(0);
  const lastHeartbeatRef = useRef(0);

  const verifySession = useCallback((force = false) => {
    if (typeof navigator !== "undefined" && !navigator.onLine) {
      markHydrated();
      return Promise.resolve();
    }
    if (verificationRef.current) return verificationRef.current;
    if (!force && Date.now() - lastVerifiedAtRef.current < SESSION_RECHECK_INTERVAL_MS) {
      return Promise.resolve();
    }

    const controller = new AbortController();
    const expectedVersion = useAuthStore.getState().sessionVersion;
    activeControllerRef.current = controller;

    const verification = authApi.getMe(controller.signal)
      .then((user) => {
        if (
          mountedRef.current &&
          !controller.signal.aborted &&
          useAuthStore.getState().sessionVersion === expectedVersion
        ) {
          setSession(user);
          lastVerifiedAtRef.current = Date.now();
        }
      })
      .catch(() => {
        // A 401 is handled centrally by the API refresh interceptor. Network
        // loss is recoverable and must not be treated as logout.
      })
      .finally(() => {
        if (mountedRef.current) markHydrated();
        if (activeControllerRef.current === controller) {
          activeControllerRef.current = null;
        }
        if (verificationRef.current === verification) {
          verificationRef.current = null;
        }
      });

    verificationRef.current = verification;
    return verification;
  }, [markHydrated, setSession]);

  useEffect(() => {
    mountedRef.current = true;
    lastHeartbeatRef.current = Date.now();
    void verifySession(true);

    const handleUsable = () => {
      if (document.visibilityState === "visible" && navigator.onLine) {
        void verifySession();
      }
    };
    const handleOnline = () => {
      void verifySession(true);
    };
    const handleVisibility = () => {
      if (document.visibilityState === "visible") handleUsable();
    };
    const handlePageShow = () => handleUsable();
    const heartbeat = window.setInterval(() => {
      const now = Date.now();
      const likelyWokeFromSleep = now - lastHeartbeatRef.current > SESSION_RECHECK_INTERVAL_MS;
      lastHeartbeatRef.current = now;
      if (likelyWokeFromSleep) handleUsable();
    }, WAKE_CHECK_INTERVAL_MS);
    const unsubscribeSessionResets = subscribeToSessionResets((reason) => {
      activeControllerRef.current?.abort();
      void clearSession(reason, {
        notifyOtherTabs: false,
        revokeServerSession: false,
      });
    });

    window.addEventListener("focus", handleUsable);
    window.addEventListener("online", handleOnline);
    window.addEventListener("pageshow", handlePageShow);
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      mountedRef.current = false;
      activeControllerRef.current?.abort();
      activeControllerRef.current = null;
      verificationRef.current = null;
      window.clearInterval(heartbeat);
      unsubscribeSessionResets();
      window.removeEventListener("focus", handleUsable);
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("pageshow", handlePageShow);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [clearSession, verifySession]);

  return null;
}

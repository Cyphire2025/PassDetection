"use client";

import { useCallback, useEffect, useRef } from "react";
import { authApi } from "../api/auth.api";
import { subscribeToSessionResets } from "../services/session-state";
import {
  refreshAuthenticatedSession,
  type ApiError,
} from "@/lib/api/client";
import { useAuthStore } from "@/stores/auth.store";

const SESSION_RECHECK_INTERVAL_MS = 60_000;
const WAKE_CHECK_INTERVAL_MS = 30_000;
const SESSION_REFRESH_FALLBACK_MS = 20 * 60_000;
const SESSION_REFRESH_SAFETY_WINDOW_MS = 2 * 60_000;
const SESSION_REFRESH_MINIMUM_DELAY_MS = 30_000;
const SESSION_REFRESH_RETRY_DELAY_MS = 30_000;

export function AuthHydrator() {
  const setSession = useAuthStore((state) => state.setSession);
  const clearSession = useAuthStore((state) => state.clearSession);
  const markHydrated = useAuthStore((state) => state.markHydrated);
  const mountedRef = useRef(false);
  const activeControllerRef = useRef<AbortController | null>(null);
  const verificationRef = useRef<Promise<void> | null>(null);
  const renewalRef = useRef<Promise<void> | null>(null);
  const renewalTimerRef = useRef<number | null>(null);
  const renewalDueAtRef = useRef(0);
  const renewSessionRef = useRef<(() => Promise<void>) | null>(null);
  const lastVerifiedAtRef = useRef(0);
  const lastHeartbeatRef = useRef(0);

  const scheduleRenewal = useCallback(
    (expiresAt: string | null, fallbackDelay = SESSION_REFRESH_FALLBACK_MS) => {
      if (typeof window === "undefined") return;
      if (renewalTimerRef.current !== null) {
        window.clearTimeout(renewalTimerRef.current);
      }
      const now = Date.now();
      const parsedExpiry = expiresAt ? Date.parse(expiresAt) : Number.NaN;
      const dueAt = Number.isFinite(parsedExpiry)
        ? Math.max(
            now + SESSION_REFRESH_MINIMUM_DELAY_MS,
            parsedExpiry - SESSION_REFRESH_SAFETY_WINDOW_MS,
          )
        : now + fallbackDelay;
      renewalDueAtRef.current = dueAt;
      renewalTimerRef.current = window.setTimeout(() => {
        void renewSessionRef.current?.();
      }, dueAt - now);
    },
    [],
  );

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

  const renewSession = useCallback(() => {
    if (renewalRef.current) return renewalRef.current;
    if (typeof navigator !== "undefined" && !navigator.onLine) {
      markHydrated();
      scheduleRenewal(null);
      return Promise.resolve();
    }

    const renewal = refreshAuthenticatedSession()
      .then(async (session) => {
        if (!mountedRef.current) return;
        if (session) {
          setSession(session.user);
          lastVerifiedAtRef.current = Date.now();
          scheduleRenewal(session.access_token_expires_at);
          return;
        }
        // Another tab may have completed the coordinated refresh. Confirm the
        // user with the new shared cookie and use a conservative next renewal.
        await verifySession(true);
        if (mountedRef.current) scheduleRenewal(null);
      })
      .catch((error: unknown) => {
        // Invalid refresh cookies are handled centrally and redirect at once.
        // A transient network failure must keep the local session intact.
        if (
          mountedRef.current
          && (error as Partial<ApiError> | null)?.code !== "AUTH_SESSION_EXPIRED"
        ) {
          scheduleRenewal(null, SESSION_REFRESH_RETRY_DELAY_MS);
        }
      })
      .finally(() => {
        if (mountedRef.current) markHydrated();
        if (renewalRef.current === renewal) renewalRef.current = null;
      });

    renewalRef.current = renewal;
    return renewal;
  }, [markHydrated, scheduleRenewal, setSession, verifySession]);

  useEffect(() => {
    renewSessionRef.current = renewSession;
    return () => {
      renewSessionRef.current = null;
    };
  }, [renewSession]);

  useEffect(() => {
    mountedRef.current = true;
    lastHeartbeatRef.current = Date.now();
    void renewSession();

    const handleUsable = () => {
      if (document.visibilityState === "visible" && navigator.onLine) {
        if (Date.now() >= renewalDueAtRef.current) {
          void renewSession();
        } else {
          void verifySession();
        }
      }
    };
    const handleOnline = () => {
      if (Date.now() >= renewalDueAtRef.current) {
        void renewSession();
      } else {
        void verifySession(true);
      }
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
      renewalRef.current = null;
      if (renewalTimerRef.current !== null) {
        window.clearTimeout(renewalTimerRef.current);
        renewalTimerRef.current = null;
      }
      window.clearInterval(heartbeat);
      unsubscribeSessionResets();
      window.removeEventListener("focus", handleUsable);
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("pageshow", handlePageShow);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [clearSession, renewSession, verifySession]);

  return null;
}

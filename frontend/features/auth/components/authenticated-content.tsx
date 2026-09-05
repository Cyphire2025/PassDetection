"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { LoadingSpinner } from "@/components/shared/loading-spinner";
import { expiredSessionSignInPath } from "../services/restoration-destination";
import {
  selectHasHydrated,
  selectIsAuthenticated,
  useAuthStore,
} from "@/stores/auth.store";

interface AuthenticatedContentProps {
  children: ReactNode;
}

/**
 * Prevents protected feature queries from mounting before the initial cookie
 * renewal has completed. This avoids a burst of expected 401 responses when a
 * long-lived browser tab returns with an expired access cookie.
 */
export function AuthenticatedContent({ children }: AuthenticatedContentProps) {
  const router = useRouter();
  const hasHydrated = useAuthStore(selectHasHydrated);
  const isAuthenticated = useAuthStore(selectIsAuthenticated);
  const restorationStatus = useAuthStore((state) => state.restorationStatus);
  const redirectStartedRef = useRef(false);

  useEffect(() => {
    if (!hasHydrated || isAuthenticated || redirectStartedRef.current) return;

    // Session cleanup normally starts this navigation from the auth store.
    // Keep the protected-content boundary independently fail-closed so a
    // rejected initial refresh can never strand the user behind a permanent
    // loading screen if cleanup or cross-tab signalling is delayed.
    redirectStartedRef.current = true;
    router.replace(expiredSessionSignInPath(window.location.pathname, window.location.search));
  }, [hasHydrated, isAuthenticated, router]);

  if (!isAuthenticated && restorationStatus === "temporarily_unavailable") {
    return (
      <div className="fixed inset-0 flex min-h-dvh items-center justify-center bg-slate-50 p-6">
        <div role="alert" className="max-w-md rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
          <h1 className="text-lg font-semibold text-slate-950">Unable to restore your session</h1>
          <p className="mt-3 text-sm leading-6 text-slate-600">
            The server is temporarily unavailable or your connection is offline. Your session has not been rejected. Reconnect and try again.
          </p>
          <button type="button" className="mt-5 rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-medium text-white focus-visible:outline-2 focus-visible:outline-offset-2"
            onClick={() => window.dispatchEvent(new Event("auth:retry-restoration"))}>
            Retry connection
          </button>
        </div>
      </div>
    );
  }

  if (!hasHydrated) {
    return (
      <div
        className="fixed inset-0 flex min-h-dvh items-center justify-center bg-slate-50"
        aria-live="polite"
      >
        <div className="flex flex-col items-center gap-3 text-sm text-slate-600">
          <LoadingSpinner size="lg" label="Restoring secure session" />
          <p>Restoring your secure session…</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div
        className="fixed inset-0 flex min-h-dvh items-center justify-center bg-slate-50"
        role="status"
        aria-live="polite"
      >
        <p className="text-sm text-slate-600">Your session ended. Returning to sign in…</p>
      </div>
    );
  }

  return children;
}

"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { LoadingSpinner } from "@/components/shared/loading-spinner";
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
  const redirectStartedRef = useRef(false);

  useEffect(() => {
    if (!hasHydrated || isAuthenticated || redirectStartedRef.current) return;

    // Session cleanup normally starts this navigation from the auth store.
    // Keep the protected-content boundary independently fail-closed so a
    // rejected initial refresh can never strand the user behind a permanent
    // loading screen if cleanup or cross-tab signalling is delayed.
    redirectStartedRef.current = true;
    router.replace("/login?reason=session_expired");
  }, [hasHydrated, isAuthenticated, router]);

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

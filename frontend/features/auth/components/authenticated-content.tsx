"use client";

import type { ReactNode } from "react";
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
  const hasHydrated = useAuthStore(selectHasHydrated);
  const isAuthenticated = useAuthStore(selectIsAuthenticated);

  if (!hasHydrated || !isAuthenticated) {
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

  return children;
}

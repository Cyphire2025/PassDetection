"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { Loader2, RefreshCw } from "lucide-react";
import { useAuthStore } from "@/stores/auth.store";
import { AuthHydrator } from "./auth-hydrator";
import { LoginForm } from "./login-form";
import { safeRestorationDestination } from "../services/restoration-destination";

/** Check the backend-owned session before starting another password/MFA login. */
export function LoginSessionEntry({ notice, from }: { notice?: string; from?: string }) {
  const router = useRouter();
  const [entryVersion] = useState(() => useAuthStore.getState().sessionVersion);
  const sessionVersion = useAuthStore(state => state.sessionVersion);
  const isAuthenticated = useAuthStore(state => state.isAuthenticated);
  const restorationStatus = useAuthStore(state => state.restorationStatus);
  const destination = safeRestorationDestination(from);
  // An in-memory user left by earlier navigation is not sufficient. Wait for
  // this entry's authoritative refresh (or rejection), including across tabs.
  const checked = sessionVersion !== entryVersion;
  const restored = checked && isAuthenticated;
  const rejected = checked && restorationStatus === "rejected";

  useEffect(() => {
    if (restored) router.replace(destination as Route);
  }, [destination, restored, router]);

  // Stop the hydrator after rejection so focus/retry timers cannot interrupt
  // a password or authenticator challenge the user is now completing.
  if (rejected) return <LoginForm notice={notice} />;

  return <>
    {!restored && <AuthHydrator />}
    {restorationStatus === "temporarily_unavailable" ? (
      <div className="space-y-5 text-[#123047]" role="alert">
        <h1 className="text-[28px] font-semibold tracking-tight">Let’s reconnect.</h1>
        <p className="text-sm leading-relaxed text-slate-600">
          We couldn’t check your saved session. Your saved session will be checked once the connection is back.
        </p>
        <button type="button" onClick={() => window.dispatchEvent(new Event("auth:retry-restoration"))}
          className="inline-flex h-12 items-center justify-center gap-2 rounded-lg bg-[#123753] px-5 text-sm font-semibold text-white hover:bg-[#17486d] focus-visible:outline-2 focus-visible:outline-offset-2">
          <RefreshCw className="h-4 w-4" aria-hidden="true" /> Retry connection
        </button>
      </div>
    ) : (
      <div className="flex items-center gap-3 text-sm text-slate-600" role="status" aria-live="polite">
        <Loader2 className="h-5 w-5 animate-spin text-[#123753]" aria-hidden="true" />
        {restored ? "Opening your workspace…" : "Checking your saved session…"}
      </div>
    )}
  </>;
}

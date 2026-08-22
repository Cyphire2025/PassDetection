"use client";

import { useEffect, useRef, useState } from "react";
import { ExternalLink, ShieldCheck, Smartphone } from "lucide-react";
import { Button, Card, CardContent } from "@/components/ui";

const TOKEN_PATTERN = /^[A-Za-z0-9_-]{32,512}$/;

export function ClientManagerActivationFallback() {
  const tokenRef = useRef<string | null>(null);
  const [linkState, setLinkState] = useState<"checking" | "ready" | "invalid">("checking");

  useEffect(() => {
    const current = new URL(window.location.href);
    const tokens = current.searchParams.getAll("token");
    const onlyExpectedParameter = [...current.searchParams.keys()].every((key) => key === "token");
    const token = tokens.length === 1 && onlyExpectedParameter && !current.hash
      ? tokens[0]
      : null;

    tokenRef.current = token && TOKEN_PATTERN.test(token) ? token : null;
    setLinkState(tokenRef.current ? "ready" : "invalid");

    // Activation credentials must not remain in history, screenshots, copied
    // addresses, or referrers after the fallback page has loaded.
    window.history.replaceState(null, "", current.pathname);
    return () => {
      tokenRef.current = null;
    };
  }, []);

  const retryVerifiedLink = () => {
    const token = tokenRef.current;
    if (!token) return;
    const verifiedLink = new URL("/gc/activate", window.location.origin);
    verifiedLink.searchParams.set("token", token);
    window.location.assign(verifiedLink.toString());
  };

  return (
    <main className="flex min-h-dvh items-center justify-center bg-slate-950 px-4 py-10">
      <Card className="w-full max-w-lg border-slate-700 bg-slate-900 text-white shadow-2xl">
        <CardContent className="space-y-6 p-6 sm:p-8">
          <div className="flex items-start gap-3">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-emerald-400/10 text-emerald-300 ring-1 ring-emerald-300/20">
              <Smartphone className="h-5 w-5" aria-hidden="true" />
            </span>
            <div>
              <h1 className="text-xl font-semibold">Open Group Companion</h1>
              <p className="mt-2 text-sm leading-6 text-slate-300">
                Client Manager activation is completed only inside the Group Companion mobile app. This website never accepts your new password or creates a dashboard session.
              </p>
            </div>
          </div>

          {linkState === "checking" && <p role="status" className="text-sm text-slate-300">Checking the activation link…</p>}
          {linkState === "invalid" && (
            <div role="alert" className="rounded-xl border border-red-400/30 bg-red-400/10 p-4 text-sm leading-6 text-red-100">
              This activation link is incomplete or malformed. Ask your administrator to issue a new single-use link.
            </div>
          )}
          {linkState === "ready" && (
            <div className="space-y-4">
              <div className="flex gap-3 rounded-xl border border-emerald-300/25 bg-emerald-300/10 p-4 text-sm leading-6 text-emerald-50">
                <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-emerald-300" aria-hidden="true" />
                <p>The credential was removed from the address bar. Tap below to retry the same verified HTTPS app link.</p>
              </div>
              <Button type="button" className="w-full" leftIcon={<ExternalLink className="h-4 w-4" aria-hidden="true" />} onClick={retryVerifiedLink}>
                Open the mobile app
              </Button>
              <p className="text-xs leading-5 text-slate-400">
                If the app still does not open, return to the approved message that contained this invitation and tap its original link after installing or updating Group Companion. Do not paste the link into another website.
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </main>
  );
}

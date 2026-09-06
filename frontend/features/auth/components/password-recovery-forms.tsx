"use client";

/* eslint-disable @next/next/no-location-assign-relative-destination -- Identity-action exits intentionally reload the document to discard credentials, MFA challenges and stale session state. */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { KeyRound, Mail } from "lucide-react";
import { Button, Input, PasswordInput } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { useAuthStore } from "@/stores/auth.store";
import { authApi } from "../api/auth.api";
import { useIdentityActionToken } from "../hooks/use-identity-action-token";
import { MfaChallengePanel } from "./login-form";

export function PasswordRecoveryRequestForm() {
  const [email, setEmail] = useState("");
  const request = useMutation({ mutationFn: () => authApi.requestPasswordRecovery(email.trim()) });

  return (
    <div className="space-y-6 text-[#123047] [&_label]:text-[#253e50]">
      <div>
        <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.025em]">Recover your account</h1>
        <p className="mt-3 text-sm leading-relaxed text-slate-600">Enter your workspace email to request a password reset.</p>
      </div>
      <Input
        label="Email address"
        type="email"
        autoComplete="email"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        leftAddon={<Mail className="h-4 w-4" aria-hidden="true" />}
        className="h-[54px] border-[#cbd5dc] text-base focus:ring-[#1d6297]"
      />
      {request.data ? (
        <div className="space-y-3 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">
          <p>{request.data.message}</p>
          {request.data.development_recovery_token && (
            <a
              className="inline-flex font-semibold underline underline-offset-2"
              href={`/recover?token=${encodeURIComponent(request.data.development_recovery_token)}`}
            >
              Continue with the development recovery link
            </a>
          )}
        </div>
      ) : (
        <Button type="button" className="h-[54px] w-full bg-[#123753] hover:bg-[#17486d] active:bg-[#102e43]" isLoading={request.isPending} disabled={!email.includes("@") || request.isPending} onClick={() => request.mutate()}>Request recovery</Button>
      )}
      {request.error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">Recovery could not be started. Please try again.</div>}
      <Button type="button" variant="secondary" className="h-[54px] w-full" onClick={() => window.location.assign("/login")}>Return to sign in</Button>
    </div>
  );
}

export function PasswordRecoveryCompleteForm() {
  const { readToken, tokenState } = useIdentityActionToken();
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const setSession = useAuthStore((state) => state.setSession);
  const recovery = useMutation({
    mutationFn: () => {
      const token = readToken();
      if (!token) throw new Error("Recovery credential is unavailable");
      return authApi.completePasswordRecovery(token, password);
    },
    onSuccess: (outcome) => {
      if (outcome.status !== "authenticated") return;
      setSession(outcome.user);
      window.location.assign(ROUTES.dashboard.root);
    },
  });

  if (recovery.data?.status === "action_completed") {
    return (
      <div className="space-y-6 text-[#123047]">
        <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.025em]">Password updated</h1>
        <p role="status" className="text-sm leading-relaxed text-slate-600">{recovery.data.message}</p>
        <Button type="button" variant="secondary" className="h-[54px] w-full" onClick={() => window.location.assign("/login")}>Return to sign in</Button>
      </div>
    );
  }
  if (recovery.data?.status === "mfa_required" || recovery.data?.status === "mfa_enrollment_required") {
    return <MfaChallengePanel challenge={recovery.data} onBack={() => window.location.assign("/login")} />;
  }
  if (tokenState === "checking") {
    return <p role="status" className="text-sm leading-relaxed text-slate-600">Checking the recovery link...</p>;
  }
  if (tokenState === "invalid") {
    return (
      <div className="space-y-6 text-[#123047]">
        <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.025em]">Recovery link unavailable</h1>
        <p className="text-sm leading-relaxed text-slate-600">Request a new recovery link to continue.</p>
        <Button type="button" className="h-[54px] w-full bg-[#123753] hover:bg-[#17486d] active:bg-[#102e43]" onClick={() => window.location.assign("/forgot-password")}>Request a new link</Button>
      </div>
    );
  }

  const submit = () => {
    setValidationError(null);
    if (password.length < 10 || !/[A-Z]/.test(password) || !/[a-z]/.test(password) || !/\d/.test(password)) {
      setValidationError("Use at least 10 characters with uppercase, lowercase, and a number.");
      return;
    }
    if (password !== confirmation) {
      setValidationError("The password confirmation does not match.");
      return;
    }
    recovery.mutate();
  };

  return (
    <div className="space-y-6 text-[#123047] [&_label]:text-[#253e50]">
      <div>
        <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.025em]">Choose a new password</h1>
        <p className="mt-3 text-sm leading-relaxed text-slate-600">Every existing session is revoked when this link is completed.</p>
      </div>
      <PasswordInput label="New password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} leftAddon={<KeyRound className="h-4 w-4" aria-hidden="true" />} className="h-[54px] border-[#cbd5dc] pr-12 text-base focus:ring-[#1d6297]" />
      <PasswordInput label="Confirm password" autoComplete="new-password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} className="h-[54px] border-[#cbd5dc] pr-12 text-base focus:ring-[#1d6297]" />
      {(validationError || recovery.error) && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{validationError ?? "The recovery link is invalid, expired, or already used."}</div>}
      <Button type="button" className="h-[54px] w-full bg-[#123753] hover:bg-[#17486d] active:bg-[#102e43]" isLoading={recovery.isPending} onClick={submit}>Reset password and continue</Button>
    </div>
  );
}

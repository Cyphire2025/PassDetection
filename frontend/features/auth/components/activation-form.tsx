"use client";

/* eslint-disable @next/next/no-location-assign-relative-destination -- Identity-action exits intentionally reload the document to discard credentials, MFA challenges and stale session state. */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { Button, PasswordInput } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { useAuthStore } from "@/stores/auth.store";
import { authApi } from "../api/auth.api";
import { useIdentityActionToken } from "../hooks/use-identity-action-token";
import { MfaChallengePanel } from "./login-form";

export function ActivationForm() {
  const { readToken, tokenState } = useIdentityActionToken();
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const setSession = useAuthStore((state) => state.setSession);
  const activation = useMutation({
    mutationFn: () => {
      const token = readToken();
      if (!token) throw new Error("Activation credential is unavailable");
      return authApi.activate(token, password);
    },
    onSuccess: (outcome) => {
      if (outcome.status !== "authenticated") return;
      setSession(outcome.user);
      window.location.assign(ROUTES.dashboard.root);
    },
  });

  if (activation.data?.status === "action_completed") {
    return (
      <div className="space-y-6 text-[#123047]">
        <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.025em]">Account activated</h1>
        <p role="status" className="text-sm leading-relaxed text-slate-600">{activation.data.message}</p>
        <Button type="button" variant="secondary" className="h-[54px] w-full" onClick={() => window.location.assign("/login")}>Return to sign in</Button>
      </div>
    );
  }

  if (activation.data?.status === "mfa_required" || activation.data?.status === "mfa_enrollment_required") {
    return (
      <MfaChallengePanel
        challenge={activation.data}
        onBack={() => window.location.assign("/login")}
      />
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
    activation.mutate();
  };

  if (tokenState === "checking") {
    return <p role="status" className="text-sm leading-relaxed text-slate-600">Checking the activation link...</p>;
  }

  if (tokenState === "invalid") {
    return (
      <div className="space-y-6 text-[#123047]">
        <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.025em]">Activation link unavailable</h1>
        <p className="text-sm leading-relaxed text-slate-600">Ask your administrator to issue a new single-use activation link.</p>
        <Button type="button" variant="secondary" className="h-[54px] w-full" onClick={() => window.location.assign("/login")}>Return to sign in</Button>
      </div>
    );
  }

  return (
    <div className="space-y-6 text-[#123047] [&_label]:text-[#253e50]">
      <div>
        <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.025em]">Activate your account</h1>
        <p className="mt-3 text-sm leading-relaxed text-slate-600">Choose a password known only to you. Staff accounts enroll MFA next.</p>
      </div>
      <PasswordInput
        label="New password"
        autoComplete="new-password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        leftAddon={<KeyRound className="h-4 w-4" aria-hidden="true" />}
        className="h-[54px] border-[#cbd5dc] pr-12 text-base focus:ring-[#1d6297]"
      />
      <PasswordInput
        label="Confirm password"
        autoComplete="new-password"
        value={confirmation}
        onChange={(event) => setConfirmation(event.target.value)}
        className="h-[54px] border-[#cbd5dc] pr-12 text-base focus:ring-[#1d6297]"
      />
      <p className="text-xs leading-relaxed text-slate-600">Use uppercase, lowercase, a number, and at least 10 characters.</p>
      {(validationError || activation.error) && (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {validationError ?? "The activation link is invalid, expired, or already used."}
        </div>
      )}
      <Button type="button" className="h-[54px] w-full bg-[#123753] hover:bg-[#17486d] active:bg-[#102e43]" isLoading={activation.isPending} onClick={submit}>Set password and continue</Button>
    </div>
  );
}

/**
 * LoginForm — Light Theme
 */

"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { KeyRound, Mail, Lock, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Button, Input, PasswordInput } from "@/components/ui";
import { loginSchema, type LoginFormData } from "../schemas/auth.schemas";
import { getSafeNextPath, useLogin } from "../hooks/use-login";
import type { ApiError } from "@/types";
import type { AuthChallenge, MFAEnrollmentSession } from "@/types";
import { authApi } from "../api/auth.api";
import { useAuthStore } from "@/stores/auth.store";

export function LoginForm({ notice }: { notice?: string }) {
  const { mutate: login, isPending, error, data, reset } = useLogin();
  const apiError = error as ApiError | null;
  const { register, handleSubmit, formState: { errors } } = useForm<LoginFormData>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });

  if (data?.status !== undefined && data.status !== "authenticated") {
    return <MfaChallengePanel challenge={data} onBack={reset} />;
  }

  return (
    <div className="bg-transparent p-3 text-white sm:p-4 [&_label]:text-white [&_label]:drop-shadow-[0_1px_2px_rgba(0,0,0,0.95)]">
      <h2 className="mb-1 text-base font-semibold text-white drop-shadow-[0_1px_2px_rgba(0,0,0,0.95)]">Sign in to your account</h2>
      <p className="mb-4 text-sm font-medium text-white drop-shadow-[0_1px_2px_rgba(0,0,0,0.95)]">
        Enter your credentials to access the platform
      </p>

      {apiError && (
        <div role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
          {apiError.message}
        </div>
      )}

      {notice && !apiError && (
        <div role="status" className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {notice}
        </div>
      )}

      <form onSubmit={handleSubmit((d) => login(d))} className="flex flex-col gap-4" noValidate>
        <Input
          {...register("email")}
          id="login-email"
          type="email"
          label="Email address"
          placeholder="you@agency.com"
          autoComplete="email"
          required
          error={errors.email?.message}
          leftAddon={<Mail className="h-4 w-4" aria-hidden="true" />}
          className="h-12 text-base"
        />

        <PasswordInput
          {...register("password")}
          id="login-password"
          label="Password"
          placeholder="••••••••"
          autoComplete="current-password"
          required
          error={errors.password?.message}
          leftAddon={<Lock className="h-4 w-4" aria-hidden="true" />}
          className="h-12 pr-12 text-base"
        />

        <Button type="submit" isLoading={isPending} className="mt-1 h-12 w-full text-base" id="login-submit">
          Sign in
        </Button>
      </form>

      <p className="mt-3 text-center text-xs font-medium text-white drop-shadow-[0_1px_2px_rgba(0,0,0,0.95)]">
        <a href="/forgot-password" className="underline decoration-white/60 underline-offset-2 hover:decoration-white">Forgot your password?</a>
      </p>
    </div>
  );
}

export function MfaChallengePanel({ challenge, onBack }: { challenge: AuthChallenge; onBack: () => void }) {
  const [code, setCode] = useState("");
  const [completed, setCompleted] = useState<MFAEnrollmentSession | null>(null);
  const setSession = useAuthStore((state) => state.setSession);
  const verify = useMutation({
    mutationFn: () => authApi.verifyMfa(challenge.challenge_token, code.trim()),
    onSuccess: (session) => {
      if (session.recovery_codes?.length) {
        setCompleted(session);
        return;
      }
      finishAuthentication(session, setSession);
    },
  });

  if (completed?.recovery_codes?.length) {
    return (
      <div className="space-y-4 bg-transparent p-3 text-white sm:p-4">
        <div>
          <h2 className="text-base font-semibold drop-shadow-[0_1px_2px_rgba(0,0,0,0.95)]">Save your recovery codes</h2>
          <p className="mt-1 text-sm font-medium drop-shadow-[0_1px_2px_rgba(0,0,0,0.95)]">Each code works once. Store them in a password manager before continuing.</p>
        </div>
        <div className="grid grid-cols-2 gap-2 rounded-xl border border-white/20 bg-slate-950/80 p-3 font-mono text-xs">
          {completed.recovery_codes.map((recoveryCode) => <span key={recoveryCode}>{recoveryCode}</span>)}
        </div>
        <Button type="button" className="w-full" onClick={() => finishAuthentication(completed, setSession)}>I saved these codes</Button>
      </div>
    );
  }

  const enrolling = challenge.status === "mfa_enrollment_required";
  return (
    <div className="space-y-4 bg-transparent p-3 text-white sm:p-4">
      <div>
        <h2 className="flex items-center gap-2 text-base font-semibold drop-shadow-[0_1px_2px_rgba(0,0,0,0.95)]">
          <ShieldCheck className="h-5 w-5" aria-hidden="true" />
          {enrolling ? "Protect your account" : "Verify your identity"}
        </h2>
        <p className="mt-1 text-sm font-medium drop-shadow-[0_1px_2px_rgba(0,0,0,0.95)]">
          {enrolling ? "Add this account to an authenticator app, then enter its six-digit code." : "Enter an authenticator code or one unused recovery code."}
        </p>
      </div>
      {enrolling && challenge.setup_secret && (
        <div className="rounded-xl border border-white/20 bg-slate-950/80 p-3">
          <p className="text-xs text-slate-200">Authenticator setup key</p>
          <p className="mt-1 break-all font-mono text-sm font-semibold tracking-wider">{challenge.setup_secret}</p>
        </div>
      )}

      <Input
        id="mfa-code"
        label="Verification code"
        value={code}
        onChange={(event) => setCode(event.target.value)}
        autoComplete="one-time-code"
        inputMode="text"
        leftAddon={<KeyRound className="h-4 w-4" aria-hidden="true" />}
      />
      {verify.error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">The code was rejected or the challenge expired. Try again.</div>}
      <div className="flex gap-2">
        <Button type="button" variant="secondary" className="flex-1" onClick={onBack} disabled={verify.isPending}>Back</Button>
        <Button type="button" className="flex-1" isLoading={verify.isPending} disabled={code.trim().length < 6} onClick={() => verify.mutate()}>Verify</Button>
      </div>
    </div>
  );
}

function finishAuthentication(
  session: MFAEnrollmentSession,
  setSession: (user: MFAEnrollmentSession["user"]) => void,
) {
  setSession(session.user);
  const params = new URLSearchParams(window.location.search);
  window.location.assign(getSafeNextPath(params.get("from")));
}

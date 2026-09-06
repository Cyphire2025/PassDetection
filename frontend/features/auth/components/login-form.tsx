/**
 * LoginForm — Light Theme
 */

"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { ArrowRight, KeyRound, Mail, Lock, ShieldCheck } from "lucide-react";
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
    <div className="text-[#123047] [&_label]:text-[#253e50]" data-login-form>
      <h1 className="text-[32px] leading-tight font-semibold tracking-[-0.035em] text-[#102e43]">Welcome back.</h1>
      <p className="mt-3 mb-8 text-sm leading-relaxed text-slate-600">
        Sign in to your Global Connect workspace.
      </p>

      {apiError && (
        <div role="alert" className="mb-6 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {apiError.message}
        </div>
      )}

      {notice && !apiError && (
        <div role="status" className="mb-6 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {notice}
        </div>
      )}

      <form onSubmit={handleSubmit((d) => login(d))} className="flex flex-col gap-6" noValidate>
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
          className="h-[54px] rounded-lg border-[#cbd5dc] bg-white text-base focus:ring-[#1d6297]"
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
          className="h-[54px] rounded-lg border-[#cbd5dc] bg-white pr-12 text-base focus:ring-[#1d6297]"
        />

        <Button
          type="submit"
          isLoading={isPending}
          className="mt-1 h-[54px] w-full rounded-lg bg-[#123753] text-sm font-semibold hover:bg-[#17486d] active:bg-[#102e43]"
          rightIcon={<ArrowRight className="h-4 w-4" aria-hidden="true" />}
          id="login-submit"
        >
          Sign in
        </Button>
      </form>

      <p className="mt-5 text-center text-sm">
        <a href="/forgot-password" className="inline-flex min-h-11 items-center font-medium text-[#1b5b8a] underline-offset-4 hover:underline">Forgot your password?</a>
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
      <div className="space-y-6 text-[#123047]">
        <div>
          <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.025em]">Save your recovery codes</h1>
          <p className="mt-3 text-sm leading-relaxed text-slate-600">Each code works once. Store them in a password manager before continuing.</p>
        </div>
        <div className="grid grid-cols-2 gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4 font-mono text-xs text-[#123047]">
          {completed.recovery_codes.map((recoveryCode) => <span className="break-all" key={recoveryCode}>{recoveryCode}</span>)}
        </div>
        <Button type="button" className="h-[54px] w-full bg-[#123753] hover:bg-[#17486d] active:bg-[#102e43]" onClick={() => finishAuthentication(completed, setSession)}>I saved these codes</Button>
      </div>
    );
  }

  const enrolling = challenge.status === "mfa_enrollment_required";
  return (
    <div className="space-y-6 text-[#123047] [&_label]:text-[#253e50]">
      <div>
        <h1 className="flex items-center gap-3 text-[28px] leading-tight font-semibold tracking-[-0.025em]">
          <ShieldCheck className="h-6 w-6 shrink-0 text-[#1b5b8a]" aria-hidden="true" />
          {enrolling ? "Protect your account" : "Verify your identity"}
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-slate-600">
          {enrolling ? "Add this account to an authenticator app, then enter its six-digit code." : "Enter an authenticator code or one unused recovery code."}
        </p>
      </div>
      {enrolling && challenge.setup_secret && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <p className="text-xs text-slate-600">Authenticator setup key</p>
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
        className="h-[54px] border-[#cbd5dc] text-base focus:ring-[#1d6297]"
      />
      {verify.error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">The code was rejected or the challenge expired. Try again.</div>}
      <div className="flex gap-3">
        <Button type="button" variant="secondary" className="h-[54px] flex-1" onClick={onBack} disabled={verify.isPending}>Back</Button>
        <Button type="button" className="h-[54px] flex-1 bg-[#123753] hover:bg-[#17486d] active:bg-[#102e43]" isLoading={verify.isPending} disabled={code.trim().length < 6} onClick={() => verify.mutate()}>Verify</Button>
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

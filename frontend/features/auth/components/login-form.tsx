/**
 * LoginForm — Light Theme
 */

"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Eye, EyeOff, Mail, Lock } from "lucide-react";
import { useState } from "react";
import { Button, Input } from "@/components/ui";
import { loginSchema, type LoginFormData } from "../schemas/auth.schemas";
import { useLogin } from "../hooks/use-login";
import type { ApiError } from "@/types";

export function LoginForm() {
  const [showPassword, setShowPassword] = useState(false);
  const { mutate: login, isPending, error } = useLogin();
  const apiError = error as ApiError | null;

  const { register, handleSubmit, formState: { errors } } = useForm<LoginFormData>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
      <h2 className="mb-1 text-base font-semibold text-slate-900">Sign in to your account</h2>
      <p className="mb-6 text-sm text-slate-500">
        Enter your credentials to access the platform
      </p>

      {apiError && (
        <div role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
          {apiError.message}
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
        />

        <Input
          {...register("password")}
          id="login-password"
          type={showPassword ? "text" : "password"}
          label="Password"
          placeholder="••••••••"
          autoComplete="current-password"
          required
          error={errors.password?.message}
          leftAddon={<Lock className="h-4 w-4" aria-hidden="true" />}
          rightAddon={
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              className="text-slate-400 hover:text-slate-600 transition-colors"
              aria-label={showPassword ? "Hide password" : "Show password"}
            >
              {showPassword
                ? <EyeOff className="h-4 w-4" aria-hidden="true" />
                : <Eye    className="h-4 w-4" aria-hidden="true" />}
            </button>
          }
        />

        <Button type="submit" isLoading={isPending} className="mt-1 w-full" id="login-submit">
          Sign in
        </Button>
      </form>

      <p className="mt-5 text-center text-xs text-slate-500">
        Contact your manager or super-admin if your access needs to be reset.
      </p>
    </div>
  );
}

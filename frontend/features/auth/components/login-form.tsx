/**
 * LoginForm — Light Theme
 */

"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Mail, Lock } from "lucide-react";
import { Button, Input, PasswordInput } from "@/components/ui";
import { loginSchema, type LoginFormData } from "../schemas/auth.schemas";
import { useLogin } from "../hooks/use-login";
import type { ApiError } from "@/types";

export function LoginForm() {
  const { mutate: login, isPending, error } = useLogin();
  const apiError = error as ApiError | null;

  const { register, handleSubmit, formState: { errors } } = useForm<LoginFormData>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });

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

        <PasswordInput
          {...register("password")}
          id="login-password"
          label="Password"
          placeholder="••••••••"
          autoComplete="current-password"
          required
          error={errors.password?.message}
          leftAddon={<Lock className="h-4 w-4" aria-hidden="true" />}
        />

        <Button type="submit" isLoading={isPending} className="mt-1 w-full" id="login-submit">
          Sign in
        </Button>
      </form>

      <p className="mt-3 text-center text-xs font-medium text-white drop-shadow-[0_1px_2px_rgba(0,0,0,0.95)]">
        Contact your manager or super-admin if your access needs to be reset.
      </p>
    </div>
  );
}

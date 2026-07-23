/**
 * useLogin — Updated for Phase 2
 * ================================
 * After login: stores session + sets cookie for middleware.
 */

"use client";

import { useMutation } from "@tanstack/react-query";
import { useAuthStore } from "@/stores/auth.store";
import { authApi } from "../api/auth.api";
import { ROUTES } from "@/constants/routes";
import type { LoginFormData } from "../schemas/auth.schemas";
import type { ApiError } from "@/types";

export function useLogin() {
  const setSession = useAuthStore((s) => s.setSession);

  return useMutation({
    mutationFn: (data: LoginFormData) => authApi.login(data),

    onSuccess: (session) => {
      setSession(session.user);

      const params = new URLSearchParams(window.location.search);
      const nextPath = getSafeNextPath(params.get("from"));
      window.location.assign(nextPath);
    },

    onError: (error: ApiError) => {
      console.error("Login failed:", error.code, error.message);
    },
  });
}

function getSafeNextPath(from: string | null) {
  if (
    !from
    || !from.startsWith("/")
    || from.startsWith("//")
    || from.includes("\\")
  ) {
    return ROUTES.dashboard.root;
  }
  const target = new URL(from, window.location.origin);
  if (target.origin !== window.location.origin) return ROUTES.dashboard.root;
  return `${target.pathname}${target.search}${target.hash}`;
}

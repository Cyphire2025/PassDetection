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
      // Store in Zustand (persisted to localStorage)
      setSession(session.user, session.tokens);

      // Set a short-lived cookie so Next.js middleware can detect auth
      // Note: In a future hardening step this becomes an httpOnly cookie set by the server
      const secureFlag = window.location.protocol === "https:" ? "; Secure" : "";
      document.cookie = [
        `access_token=${encodeURIComponent(session.tokens.access_token)}`,
        "Path=/",
        "SameSite=Lax",
        "Max-Age=1800",
        secureFlag.replace("; ", ""),
      ].filter(Boolean).join("; ");

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
  if (!from || !from.startsWith("/") || from.startsWith("//")) {
    return ROUTES.dashboard.root;
  }
  return from;
}

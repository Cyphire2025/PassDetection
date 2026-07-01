/**
 * useLogin — Updated for Phase 2
 * ================================
 * After login: stores session + sets cookie for middleware.
 */

"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/stores/auth.store";
import { authApi } from "../api/auth.api";
import { ROUTES } from "@/constants/routes";
import type { LoginFormData } from "../schemas/auth.schemas";
import type { ApiError } from "@/types";

export function useLogin() {
  const router     = useRouter();
  const setSession = useAuthStore((s) => s.setSession);

  return useMutation({
    mutationFn: (data: LoginFormData) => authApi.login(data),

    onSuccess: (session) => {
      // Store in Zustand (persisted to localStorage)
      setSession(session.user, session.tokens);

      // Set a short-lived cookie so Next.js middleware can detect auth
      // Note: In a future hardening step this becomes an httpOnly cookie set by the server
      document.cookie = `access_token=${session.tokens.access_token}; path=/; SameSite=Strict; Max-Age=1800`;

      router.push(ROUTES.dashboard.root);
    },

    onError: (error: ApiError) => {
      console.error("Login failed:", error.code, error.message);
    },
  });
}

/**
 * useLogout — Logout mutation hook
 * ==================================
 * Calls the backend /auth/logout, clears local session, redirects to login.
 */

"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { authApi } from "../api/auth.api";
import { useAuthStore } from "@/stores/auth.store";
import { ROUTES } from "@/constants/routes";

export function useLogout() {
  const router        = useRouter();
  const clearSession  = useAuthStore((s) => s.clearSession);
  const tokens        = useAuthStore((s) => s.tokens);

  return useMutation({
    mutationFn: async () => {
      if (tokens?.refresh_token) {
        try {
          await authApi.logout(tokens.refresh_token);
        } catch {
          // Best-effort — clear locally even if server call fails
        }
      }
    },
    onSettled: () => {
      clearSession();
      // Remove the auth cookie
      document.cookie = "access_token=; Max-Age=0; path=/";
      router.push(ROUTES.auth.login);
    },
  });
}

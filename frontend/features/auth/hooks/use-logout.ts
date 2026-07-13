/**
 * useLogout
 * =========
 * Revokes the backend httpOnly cookie session and clears local UI state.
 */

"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { authApi } from "../api/auth.api";
import { useAuthStore } from "@/stores/auth.store";
import { ROUTES } from "@/constants/routes";

export function useLogout() {
  const router = useRouter();
  const clearSession = useAuthStore((s) => s.clearSession);

  return useMutation({
    mutationFn: async () => {
      try {
        await authApi.logout();
      } catch {
        // Best-effort: clear locally even if the server call fails.
      }
    },
    onSettled: () => {
      clearSession();
      router.push(ROUTES.auth.login);
    },
  });
}

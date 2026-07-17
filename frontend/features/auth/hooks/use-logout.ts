/**
 * useLogout
 * =========
 * Revokes the backend httpOnly cookie session and clears local UI state.
 */

"use client";

import { useMutation } from "@tanstack/react-query";
import { useAuthStore } from "@/stores/auth.store";

export function useLogout() {
  const clearSession = useAuthStore((s) => s.clearSession);

  return useMutation({
    mutationFn: () => clearSession("logout"),
  });
}

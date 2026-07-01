/**
 * useMe — Fetch current authenticated user
 * ==========================================
 * Fetches the authenticated user's profile from /auth/me.
 * Used to hydrate the auth store after page reload.
 */

import { useQuery } from "@tanstack/react-query";
import { authApi } from "../api/auth.api";
import { useAuthStore } from "@/stores/auth.store";
import { QUERY_KEYS } from "@/constants";

export function useMe() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const updateUser = useAuthStore((s) => s.updateUser);

  return useQuery({
    queryKey: QUERY_KEYS.auth.me,
    queryFn: async () => {
      const user = await authApi.getMe();
      updateUser(user);
      return user;
    },
    enabled: isAuthenticated,
    staleTime: 5 * 60 * 1000,   // 5 minutes
    retry: false,                 // Don't retry auth failures
  });
}

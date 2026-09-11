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
  const isChangingAccessLevel = useAuthStore((s) => s.isChangingAccessLevel);
  const updateUser = useAuthStore((s) => s.updateUser);

  return useQuery({
    queryKey: QUERY_KEYS.auth.me,
    queryFn: async ({ signal }) => {
      const expectedVersion = useAuthStore.getState().sessionVersion;
      const user = await authApi.getMe(signal);
      if (!signal.aborted && useAuthStore.getState().sessionVersion === expectedVersion) {
        updateUser(user);
      }
      return user;
    },
    enabled: isAuthenticated && !isChangingAccessLevel,
    staleTime: 5 * 60 * 1000,   // 5 minutes
    retry: false,                 // Don't retry auth failures
  });
}

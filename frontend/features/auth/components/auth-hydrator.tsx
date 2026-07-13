"use client";

import { useEffect } from "react";
import { authApi } from "../api/auth.api";
import { useAuthStore } from "@/stores/auth.store";

export function AuthHydrator() {
  const setSession = useAuthStore((state) => state.setSession);
  const clearSession = useAuthStore((state) => state.clearSession);
  const markHydrated = useAuthStore((state) => state.markHydrated);

  useEffect(() => {
    let cancelled = false;

    authApi.getMe()
      .then((user) => {
        if (!cancelled) setSession(user);
      })
      .catch(() => {
        if (!cancelled) clearSession();
      })
      .finally(() => {
        if (!cancelled) markHydrated();
      });

    const handleExpired = () => clearSession();
    window.addEventListener("passdetection:auth-expired", handleExpired);
    return () => {
      cancelled = true;
      window.removeEventListener("passdetection:auth-expired", handleExpired);
    };
  }, [clearSession, markHydrated, setSession]);

  return null;
}

/**
 * Apply a successful server-owned session only to the identity operation that started it.
 */

"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { RequestOwnerChangedError } from "@/lib/api/request-owner";
import { useAuthStore } from "@/stores/auth.store";
import { authApi } from "../api/auth.api";
import { ROUTES } from "@/constants/routes";
import type { LoginFormData } from "../schemas/auth.schemas";
import type { ApiError } from "@/types";
import { authenticationContextIsCurrent, captureAuthenticationContext } from "../services/authentication-context";

export function useLogin() {
  const [entryAuthentication] = useState(captureAuthenticationContext);
  const setSession = useAuthStore((s) => s.setSession);

  return useMutation({
    mutationFn: (data: LoginFormData) => {
      if (!authenticationContextIsCurrent(entryAuthentication)) throw new RequestOwnerChangedError();
      return authApi.login(data);
    },
    onMutate: captureAuthenticationContext,

    onSuccess: (session, _credentials, authentication) => {
      if (!authenticationContextIsCurrent(authentication)) return;
      if (session.status !== "authenticated") return;
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

export function getSafeNextPath(from: string | null) {
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

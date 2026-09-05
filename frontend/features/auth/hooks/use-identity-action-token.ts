"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const TOKEN_PATTERN = /^[A-Za-z0-9_-]{32,512}$/;

export type IdentityActionTokenState = "checking" | "ready" | "invalid";

export function useIdentityActionToken() {
  const tokenRef = useRef<string | null>(null);
  const capturedRef = useRef(false);
  const activeRef = useRef(false);
  const [tokenState, setTokenState] =
    useState<IdentityActionTokenState>("checking");

  useEffect(() => {
    activeRef.current = true;
    if (!capturedRef.current) {
      capturedRef.current = true;
      const current = new URL(window.location.href);
      const tokens = current.searchParams.getAll("token");
      const onlyExpectedParameter = [...current.searchParams.keys()].every(
        (key) => key === "token",
      );
      const token =
        tokens.length === 1 && onlyExpectedParameter && !current.hash
          ? tokens[0]
          : null;

      tokenRef.current = token && TOKEN_PATTERN.test(token) ? token : null;
      window.history.replaceState(window.history.state, "", current.pathname);
    }
    setTokenState(tokenRef.current ? "ready" : "invalid");

    return () => {
      activeRef.current = false;
      // Strict Mode replays setup immediately after cleanup. Keep the captured
      // credential for that replay, then discard it after a real unmount.
      queueMicrotask(() => {
        if (!activeRef.current) tokenRef.current = null;
      });
    };
  }, []);

  const readToken = useCallback(
    () => (activeRef.current ? tokenRef.current : null),
    [],
  );
  return { readToken, tokenState };
}

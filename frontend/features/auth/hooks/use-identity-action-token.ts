"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const TOKEN_PATTERN = /^[A-Za-z0-9_-]{32,512}$/;

export type IdentityActionTokenState = "checking" | "ready" | "invalid";

export function useIdentityActionToken() {
  const tokenRef = useRef<string | null>(null);
  const [tokenState, setTokenState] = useState<IdentityActionTokenState>("checking");

  useEffect(() => {
    const current = new URL(window.location.href);
    const tokens = current.searchParams.getAll("token");
    const onlyExpectedParameter = [...current.searchParams.keys()].every((key) => key === "token");
    const token = tokens.length === 1 && onlyExpectedParameter && !current.hash
      ? tokens[0]
      : null;

    tokenRef.current = token && TOKEN_PATTERN.test(token) ? token : null;
    setTokenState(tokenRef.current ? "ready" : "invalid");
    window.history.replaceState(null, "", current.pathname);

    return () => {
      tokenRef.current = null;
    };
  }, []);

  const readToken = useCallback(() => tokenRef.current, []);
  return { readToken, tokenState };
}

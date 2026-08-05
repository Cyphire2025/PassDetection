import { useCallback, useEffect, useRef, useState } from 'react';

import { deactivateLocalSession, logoutSession } from './session-service';
import { useSessionStore } from './session-store';
import { principalAccountNamespace } from './types';

type SafeSignOutResult =
  | Readonly<{ ok: true; namespace: null }>
  | Readonly<{ ok: false; namespace: string | null }>;

let activeSignOut: Promise<SafeSignOutResult> | null = null;

function singleFlight(task: () => Promise<SafeSignOutResult>): Promise<SafeSignOutResult> {
  if (activeSignOut) return activeSignOut;
  const request = Promise.resolve()
    .then(task)
    .catch((): SafeSignOutResult => ({ ok: false, namespace: null }))
    .finally(() => {
      if (activeSignOut === request) activeSignOut = null;
    });
  activeSignOut = request;
  return request;
}

export function requestSafeSignOut(): Promise<SafeSignOutResult> {
  const principal = useSessionStore.getState().session?.principal;
  const namespace = principal ? principalAccountNamespace(principal) : null;
  return singleFlight(async () => {
    try {
      await logoutSession();
      return { ok: true, namespace: null };
    } catch {
      // logoutSession clears in-memory authentication before local deactivation. Do
      // not expose filesystem/keychain errors or allow an unhandled rejection.
      return { ok: false, namespace };
    }
  });
}

export function retrySafeSignOutCleanup(namespace: string): Promise<SafeSignOutResult> {
  return singleFlight(async () => {
    try {
      await deactivateLocalSession(namespace);
      return { ok: true, namespace: null };
    } catch {
      return { ok: false, namespace };
    }
  });
}

const SAFE_CLEANUP_ERROR =
  'Signed out locally, but secure session deactivation is incomplete. Try again or contact support.';

export function useSafeSignOut() {
  const [isSigningOut, setIsSigningOut] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const activeRequest = useRef<Promise<void> | null>(null);
  const failedNamespace = useRef<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const run = useCallback((request: () => Promise<SafeSignOutResult>): Promise<void> => {
    if (activeRequest.current) return activeRequest.current;
    if (mounted.current) {
      setIsSigningOut(true);
      setErrorMessage(null);
    }
    const operation = request()
      .then((result) => {
        failedNamespace.current = result.ok ? null : result.namespace;
        if (mounted.current && !result.ok) setErrorMessage(SAFE_CLEANUP_ERROR);
      })
      .finally(() => {
        if (activeRequest.current === operation) activeRequest.current = null;
        if (mounted.current) setIsSigningOut(false);
      });
    activeRequest.current = operation;
    return operation;
  }, []);

  const signOut = useCallback(() => run(requestSafeSignOut), [run]);
  const retryCleanup = useCallback(() => {
    const namespace = failedNamespace.current;
    return namespace ? run(() => retrySafeSignOutCleanup(namespace)) : run(requestSafeSignOut);
  }, [run]);

  return { errorMessage, isSigningOut, retryCleanup, signOut } as const;
}

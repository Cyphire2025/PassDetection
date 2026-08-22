import { useCallback, useEffect, useRef, useState } from 'react';

import { cancelDepartureReminders } from '@/core/notifications/departure-reminders';
import {
  type DurableActionQueueSummary,
  UnsynchronizedActionsError,
} from '@/core/storage/pending-action-safety';
import { requestSync } from '@/core/sync/sync-trigger';

import { lockLocalSession, logoutSession } from './session-service';
import { useSessionStore } from './session-store';
import { principalAccountNamespace } from './types';

type SafeSignOutResult =
  | Readonly<{ ok: true; namespace: null }>
  | Readonly<{
      ok: false;
      namespace: string | null;
      reason: 'cleanup' | 'sync';
    }>
  | Readonly<{
      ok: false;
      namespace: string;
      reason: 'unsynchronized';
      summary: DurableActionQueueSummary;
    }>;

let activeSignOut: Promise<SafeSignOutResult> | null = null;

function singleFlight(task: () => Promise<SafeSignOutResult>): Promise<SafeSignOutResult> {
  if (activeSignOut) return activeSignOut;
  const request = Promise.resolve()
    .then(task)
    .catch((): SafeSignOutResult => ({ ok: false, namespace: null, reason: 'cleanup' }))
    .finally(() => {
      if (activeSignOut === request) activeSignOut = null;
    });
  activeSignOut = request;
  return request;
}

export function requestSafeSignOut(
  options: Readonly<{ discardUnsynchronizedActions?: boolean }> = {},
): Promise<SafeSignOutResult> {
  const principal = useSessionStore.getState().session?.principal;
  const namespace = principal ? principalAccountNamespace(principal) : null;
  return singleFlight(async () => {
    try {
      await logoutSession(options);
      await cancelDepartureReminders().catch(() => undefined);
      return { ok: true, namespace: null };
    } catch (error) {
      if (namespace && error instanceof UnsynchronizedActionsError) {
        return { ok: false, namespace, reason: 'unsynchronized', summary: error.summary };
      }
      // Do not expose filesystem/keychain errors or allow an unhandled rejection.
      return { ok: false, namespace, reason: 'cleanup' };
    }
  });
}

export function retrySafeSignOutCleanup(namespace: string): Promise<SafeSignOutResult> {
  return singleFlight(async () => {
    try {
      const principal = useSessionStore.getState().session?.principal;
      if (principal && principalAccountNamespace(principal) === namespace) {
        await logoutSession();
      } else {
        await lockLocalSession(namespace);
      }
      return { ok: true, namespace: null };
    } catch {
      return { ok: false, namespace, reason: 'cleanup' };
    }
  });
}

const SAFE_CLEANUP_ERROR =
  'Sign-out could not finish securely locking local data. Try again or contact support.';
const SAFE_SYNC_ERROR =
  'Synchronization did not finish. Your local changes are still protected on this device.';

function unsynchronizedMessage(summary: DurableActionQueueSummary): string {
  const scanCount = summary.unsynchronizedAttendanceScans;
  const otherCount = summary.unsynchronizedOtherActions;
  const scanLabel = `${scanCount} ${scanCount === 1 ? 'scan has' : 'scans have'}`;
  if (otherCount === 0) return `${scanLabel} not reached the server.`;
  return `${scanLabel} not reached the server, with ${otherCount} other unsynchronized ${
    otherCount === 1 ? 'change' : 'changes'
  }.`;
}

export function useSafeSignOut() {
  const [isSigningOut, setIsSigningOut] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [blockedActions, setBlockedActions] = useState<DurableActionQueueSummary | null>(null);
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
        if (result.ok) {
          failedNamespace.current = null;
          if (mounted.current) {
            setBlockedActions(null);
            setErrorMessage(null);
          }
          return;
        }
        failedNamespace.current = result.reason === 'cleanup' ? result.namespace : null;
        if (!mounted.current) return;
        if (result.reason === 'unsynchronized') {
          setBlockedActions(result.summary);
          setErrorMessage(unsynchronizedMessage(result.summary));
        } else {
          setErrorMessage(result.reason === 'sync' ? SAFE_SYNC_ERROR : SAFE_CLEANUP_ERROR);
        }
      })
      .finally(() => {
        if (activeRequest.current === operation) activeRequest.current = null;
        if (mounted.current) setIsSigningOut(false);
      });
    activeRequest.current = operation;
    return operation;
  }, []);

  const signOut = useCallback(() => run(requestSafeSignOut), [run]);
  const synchronizeAndSignOut = useCallback(() => run(async () => {
    const principal = useSessionStore.getState().session?.principal;
    const namespace = principal ? principalAccountNamespace(principal) : null;
    try {
      await requestSync({ scope: 'full', reason: 'sign-out-guard' });
    } catch {
      return { ok: false, namespace, reason: 'sync' } as const;
    }
    return requestSafeSignOut();
  }), [run]);
  const discardAndSignOut = useCallback(
    () => run(() => requestSafeSignOut({ discardUnsynchronizedActions: true })),
    [run],
  );
  const retryCleanup = useCallback(() => {
    const namespace = failedNamespace.current;
    return namespace ? run(() => retrySafeSignOutCleanup(namespace)) : run(requestSafeSignOut);
  }, [run]);

  return {
    blockedActions,
    discardAndSignOut,
    errorMessage,
    isSigningOut,
    retryCleanup,
    signOut,
    synchronizeAndSignOut,
  } as const;
}

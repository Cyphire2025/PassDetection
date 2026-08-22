import { closeAccountDatabase } from '@/core/storage/database';
import {
  recordAuthenticationLockOutcome,
  recordAuthenticationQuarantineDepth,
} from '@/core/observability/authentication-observability';
import {
  clearAuthenticationLockPending,
  clearNamespaceAuthentication,
  clearOfflineAuthorizationRecord,
  getPendingAuthenticationLocks,
  markAuthenticationLockPending,
} from '@/core/storage/secure-store';
import { purgeTemporaryViews } from '@/core/storage/vault';
import { cancelRequiredPreparation } from '@/core/sync/required-preparation-lease';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

import {
  invalidateAuthenticationBoundary,
  useSessionStore,
} from './session-store';
import { principalAccountNamespace, type MobileSession } from './types';

let offlineAuthorizationExpiryTimer: ReturnType<typeof setTimeout> | null = null;

export function clearOfflineAuthorizationExpiryTimer(): void {
  if (offlineAuthorizationExpiryTimer !== null) {
    clearTimeout(offlineAuthorizationExpiryTimer);
    offlineAuthorizationExpiryTimer = null;
  }
}

export function armOfflineAuthorizationExpiryTimer(
  session: MobileSession,
  namespace: string,
  remainingMs: number,
): void {
  clearOfflineAuthorizationExpiryTimer();
  const boundedDelay = Math.max(0, Math.min(Math.floor(remainingMs), 2_147_483_647));
  offlineAuthorizationExpiryTimer = setTimeout(() => {
    offlineAuthorizationExpiryTimer = null;
    const current = useSessionStore.getState().session;
    if (
      !current
      || current.networkMode !== 'offline'
      || current.sessionId !== session.sessionId
      || principalAccountNamespace(current.principal) !== namespace
    ) return;

    // Lease expiry is an immediate authentication boundary even if the durable
    // lock marker cannot be written. The encrypted queue remains untouched.
    invalidateAuthenticationBoundary();
    cancelRequiredPreparation(current.sessionId);
    useSessionStore.getState().clear();
    useSelectedTripStore.getState().clear();
    void lockLocalSession(namespace).catch(() => (
      clearOfflineAuthorizationRecord(namespace).catch(() => undefined)
    ));
  }, boundedDelay);
}

export async function lockLocalSession(
  namespace: string,
  options: Readonly<{ invalidateBoundary?: boolean }> = {},
): Promise<void> {
  const activeSession = useSessionStore.getState().session;
  const ownsActiveBoundary = activeSession
    ? principalAccountNamespace(activeSession.principal) === namespace
    : true;

  let lockError: unknown;
  let outcome: 'success' | 'failure' = 'failure';
  try {
    // Persist the fail-closed intent before changing authentication. Bootstrap
    // retries an interrupted lock without deleting encrypted data or its keys.
    await markAuthenticationLockPending(namespace);
    if (options.invalidateBoundary) invalidateAuthenticationBoundary();

    try {
      await clearNamespaceAuthentication(namespace);
    } catch (error) {
      lockError = error;
    }

    if (ownsActiveBoundary) {
      clearOfflineAuthorizationExpiryTimer();
      if (activeSession?.sessionId) cancelRequiredPreparation(activeSession.sessionId);
      useSessionStore.getState().clear();
      useSelectedTripStore.getState().clear();

      try {
        await closeAccountDatabase();
      } catch (error) {
        lockError ??= error;
      }
      try {
        await purgeTemporaryViews();
      } catch (error) {
        lockError ??= error;
      }
    }

    if (!lockError) {
      try {
        await clearAuthenticationLockPending(namespace);
      } catch (error) {
        lockError = error;
      }
    }
    if (lockError) throw lockError;
    outcome = 'success';
  } finally {
    recordAuthenticationLockOutcome(outcome);
  }
}

export async function retryPendingAuthenticationLockForNamespace(
  namespace: string,
): Promise<void> {
  if ((await getPendingAuthenticationLocks()).includes(namespace)) {
    await lockLocalSession(namespace);
  }
}

export async function retryPendingAuthenticationLocks(): Promise<Set<string>> {
  for (const namespace of await getPendingAuthenticationLocks()) {
    // A failed lock must never restore an account, but it must retain the
    // encrypted queue and its encryption keys for same-account recovery.
    await lockLocalSession(namespace).catch(() => undefined);
  }
  const pending = new Set(await getPendingAuthenticationLocks());
  recordAuthenticationQuarantineDepth(pending.size);
  return pending;
}

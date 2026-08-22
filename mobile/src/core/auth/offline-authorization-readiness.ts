import {
  compareAndSetOfflineAuthorizationRecord,
  getInstallationId,
  getOfflineAuthorizationRecord,
} from '@/core/storage/secure-store';

import {
  authorizeStoredOfflineLease,
  OfflineAuthorizationError,
} from './offline-authorization';
import {
  captureAuthenticationSnapshot,
  isAuthenticationSnapshotCurrent,
  useSessionStore,
} from './session-store';
import { principalAccountNamespace } from './types';

export type OfflineAuthorizationReadiness = Readonly<{
  remainingMs: number;
  trustedServerTimeMs: number;
}>;

/**
 * Revalidates the signed, installation-bound lease for pre-event readiness.
 * The compact lease and private verification details never leave this module.
 */
export async function offlineAuthorizationReadiness(): Promise<OfflineAuthorizationReadiness> {
  const session = useSessionStore.getState().session;
  if (!session) throw new Error('Authentication is required.');
  const authenticationSnapshot = captureAuthenticationSnapshot();
  const namespace = principalAccountNamespace(session.principal);
  const sessionStillCurrent = () => {
    const current = useSessionStore.getState().session;
    return isAuthenticationSnapshotCurrent(authenticationSnapshot)
      && current?.sessionId === session.sessionId
      && current?.accessToken === session.accessToken
      && principalAccountNamespace(current.principal) === namespace;
  };
  try {
    const [record, installationId] = await Promise.all([
      getOfflineAuthorizationRecord(namespace),
      getInstallationId(),
    ]);
    if (!record || !sessionStillCurrent()) {
      throw new OfflineAuthorizationError('clock_unavailable');
    }
    const authorization = authorizeStoredOfflineLease(record, {
      installationId,
      sessionId: session.sessionId,
      principalId: session.principal.id,
      accountId: session.principal.accountId,
      agencyId: session.principal.agencyId,
      principalType: session.principal.principalType,
      passengerId: session.principal.passengerId ?? null,
    });
    if (!sessionStillCurrent()) throw new OfflineAuthorizationError('clock_unavailable');
    const persisted = await compareAndSetOfflineAuthorizationRecord(
      namespace,
      record,
      authorization.record,
    );
    if (!persisted || !sessionStillCurrent()) {
      throw new OfflineAuthorizationError('clock_unavailable');
    }
    return {
      remainingMs: authorization.remainingMs,
      trustedServerTimeMs: authorization.trustedServerTimeMs,
    };
  } catch (error) {
    if (error instanceof OfflineAuthorizationError) throw error;
    throw new OfflineAuthorizationError('clock_unavailable');
  }
}

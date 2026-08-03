import type { MobileSession } from '@/core/auth/types';
import { useSessionStore } from '@/core/auth/session-store';

import {
  SyncContextChangedError,
  assertSyncContextActive,
  captureSyncContext,
} from '../sync-context';

function session(account: 'a' | 'b', accessToken = `access-${account}`): MobileSession {
  return {
    accessToken,
    accessTokenExpiresAt: '2030-01-01T00:00:00.000Z',
    refreshTokenExpiresAt: '2030-02-01T00:00:00.000Z',
    sessionId: `session-${account}`,
    networkMode: 'online',
    principal: {
      id: `principal-${account}`,
      accountId: `principal-${account}`,
      principalType: 'passenger',
      agencyId: `agency-${account}`,
      displayName: `Account ${account}`,
      email: null,
      phoneNumber: null,
      forcePasswordChange: false,
    },
  };
}

describe('immutable synchronization context', () => {
  afterEach(() => useSessionStore.getState().clear());

  it('survives token rotation but aborts immediately when the account changes', () => {
    useSessionStore.getState().setSession(session('a'));
    const lease = captureSyncContext();

    expect(Object.isFrozen(lease.context)).toBe(true);
    expect(lease.context.namespace).toBe('agency-a.principal-a');
    useSessionStore.getState().setSession(session('a', 'rotated-access-a'));
    expect(() => assertSyncContextActive(lease.context)).not.toThrow();
    expect(lease.context.signal.aborted).toBe(false);

    useSessionStore.getState().setSession(session('b'));
    expect(lease.context.signal.aborted).toBe(true);
    expect(() => assertSyncContextActive(lease.context)).toThrow(SyncContextChangedError);
    lease.release();
  });

  it('invalidates a captured context when the same principal starts a new session', () => {
    const original = session('a');
    useSessionStore.getState().setSession(original);
    const lease = captureSyncContext();

    useSessionStore.getState().setSession({ ...original, sessionId: 'replacement-session-a' });
    expect(() => assertSyncContextActive(lease.context)).toThrow(SyncContextChangedError);
    lease.release();
  });

  it('keeps the encrypted namespace stable but invalidates work after a passenger identity switch', () => {
    const original = session('a');
    useSessionStore.getState().setSession(original);
    const lease = captureSyncContext();

    useSessionStore.getState().setSession({
      ...original,
      principal: {
        ...original.principal,
        id: 'selected-passenger-for-another-trip',
      },
    });

    expect(lease.context.namespace).toBe('agency-a.principal-a');
    expect(lease.context.signal.aborted).toBe(true);
    expect(() => assertSyncContextActive(lease.context)).toThrow(SyncContextChangedError);
    lease.release();
  });
});

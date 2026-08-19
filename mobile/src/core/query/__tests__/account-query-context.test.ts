import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';
import { SyncContextChangedError, assertSyncContextActive } from '@/core/sync/sync-context';

import { withAccountQueryContext } from '../account-query-context';

function session(account: 'a' | 'b'): MobileSession {
  return {
    accessToken: `access-${account}`,
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

describe('withAccountQueryContext', () => {
  afterEach(() => useSessionStore.getState().clear());

  it('pins the account identity and rejects a late result after account switch', async () => {
    useSessionStore.getState().setSession(session('a'));
    const queryController = new AbortController();
    let finishOperation!: () => void;
    const operation = withAccountQueryContext(queryController.signal, async (context) => {
      expect(context.namespace).toBe('agency-a.principal-a');
      await new Promise<void>((resolve) => {
        finishOperation = resolve;
      });
      assertSyncContextActive(context);
      return 'account-a-result';
    });

    useSessionStore.getState().setSession(session('b'));
    finishOperation();

    await expect(operation).rejects.toBeInstanceOf(SyncContextChangedError);
  });

  it('combines TanStack cancellation with the account-session signal', async () => {
    useSessionStore.getState().setSession(session('a'));
    const queryController = new AbortController();
    const observedSignals: AbortSignal[] = [];
    const operation = withAccountQueryContext(queryController.signal, async (context) => {
      observedSignals.push(context.signal);
      await new Promise<void>((resolve) => {
        context.signal.addEventListener('abort', () => resolve(), { once: true });
      });
      assertSyncContextActive(context);
      return 'unreachable';
    });

    queryController.abort();

    await expect(operation).rejects.toBeInstanceOf(SyncContextChangedError);
    expect(observedSignals[0]?.aborted).toBe(true);
  });
});

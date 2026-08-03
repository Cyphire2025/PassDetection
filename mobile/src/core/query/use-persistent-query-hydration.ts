import { useQueryClient, type QueryKey } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';

type PersistentQueryHydrationOptions<T> = {
  /** Immutable tenant/account boundary already present in the React Query key. */
  accountKey: string | null;
  /** Stable identity for the persisted resource within the account boundary. */
  hydrationKey: string | null;
  queryKey: QueryKey;
  load: () => Promise<T | null | undefined>;
};

/**
 * Gates a network query until its account-scoped in-memory or persistent cache
 * has been considered. React Query otherwise starts its query during the same
 * commit in which an effect begins SQLite hydration, allowing a fast response
 * to race (and visually replace) the offline snapshot.
 *
 * A cache read failure deliberately opens the network gate: corrupt or
 * unavailable local state must not dead-end an otherwise authorized online
 * request. Account changes cancel the old hydration and its result is never
 * inserted into the new account's query cache.
 */
export function usePersistentQueryHydration<T>({
  accountKey,
  hydrationKey,
  queryKey,
  load,
}: PersistentQueryHydrationOptions<T>): boolean {
  const queryClient = useQueryClient();
  const sessionId = useSessionStore((state) => state.session?.sessionId ?? null);
  const [readyHydrationKey, setReadyHydrationKey] = useState<string | null>(null);
  const scopedHydrationKey = accountKey && hydrationKey && sessionId
    ? `${accountKey}\u001f${sessionId}\u001f${hydrationKey}`
    : null;

  useEffect(() => {
    if (!accountKey || !scopedHydrationKey) return;

    const expectedAccount = accountKey;
    const expectedSessionId = sessionId;
    let active = true;
    const accountIsCurrent = () => {
      const session = useSessionStore.getState().session;
      return Boolean(
        session
        && session.sessionId === expectedSessionId
        && principalAccountNamespace(session.principal) === expectedAccount,
      );
    };

    void (async () => {
      if (queryClient.getQueryData(queryKey) === undefined) {
        let cachedValue: T | null | undefined;
        try {
          cachedValue = await load();
        } catch {
          // The online query remains the recovery path for an unreadable cache.
        }

        if (!active || !accountIsCurrent()) return;
        if (
          cachedValue !== null
          && cachedValue !== undefined
          && queryClient.getQueryData(queryKey) === undefined
        ) {
          queryClient.setQueryData(queryKey, cachedValue);
        }
      }

      if (active && accountIsCurrent()) {
        setReadyHydrationKey(scopedHydrationKey);
      }
    })();

    return () => {
      active = false;
    };
  }, [accountKey, load, queryClient, queryKey, scopedHydrationKey, sessionId]);

  return scopedHydrationKey !== null && readyHydrationKey === scopedHydrationKey;
}

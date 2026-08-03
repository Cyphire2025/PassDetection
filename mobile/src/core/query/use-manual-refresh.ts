import { useCallback, useEffect, useRef, useState } from 'react';

type RefreshAction = () => Promise<unknown> | unknown;

/**
 * Owns only the spinner for a deliberate pull-to-refresh gesture.
 * Background React Query fetches must not be wired to this state.
 */
export function useManualRefresh() {
  const [isRefreshing, setIsRefreshing] = useState(false);
  const activeRefresh = useRef<Promise<void> | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const refresh = useCallback((action: RefreshAction): Promise<void> => {
    if (activeRefresh.current) return activeRefresh.current;
    setIsRefreshing(true);
    const request = Promise.resolve()
      .then(action)
      // Query state retains the actionable error. Pull-to-refresh must always
      // settle cleanly so a failed network request cannot leave the indicator on.
      .catch(() => undefined)
      .then(() => undefined)
      .finally(() => {
        if (activeRefresh.current === request) activeRefresh.current = null;
        if (mounted.current) setIsRefreshing(false);
      });
    activeRefresh.current = request;
    return request;
  }, []);

  return { isRefreshing, refresh } as const;
}

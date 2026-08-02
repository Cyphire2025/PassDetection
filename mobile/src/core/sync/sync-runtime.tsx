import NetInfo from '@react-native-community/netinfo';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { AppState } from 'react-native';

import { useSessionStore } from '@/core/auth/session-store';
import { isDemoMode } from '@/core/demo/demo-mode';

import { installAccessDeniedPurge, purgeExpiredTripCaches, subscribeTripPurges } from './access-cache';
import { registerBackgroundSync, unregisterBackgroundSync } from './background-sync';
import { syncAllTrips } from './sync-service';

export function SyncRuntime() {
  const demoMode = isDemoMode();
  const session = useSessionStore((state) => state.session);
  const queryClient = useQueryClient();
  const running = useRef<Promise<unknown> | null>(null);

  useEffect(() => (demoMode ? undefined : installAccessDeniedPurge()), [demoMode]);

  useEffect(() => {
    if (demoMode) return;
    return subscribeTripPurges((tripId) => {
      void queryClient.cancelQueries({ predicate: (query) => query.queryKey.includes(tripId) });
      queryClient.removeQueries({ predicate: (query) => query.queryKey.includes(tripId) });
      void queryClient.invalidateQueries({ queryKey: ['mobile-trips'] });
    });
  }, [demoMode, queryClient]);

  useEffect(() => {
    if (demoMode) {
      void unregisterBackgroundSync().catch(() => undefined);
      return;
    }
    if (!session) {
      void unregisterBackgroundSync().catch(() => undefined);
      return;
    }
    void registerBackgroundSync().catch(() => undefined);
    const refresh = () => {
      if (running.current) return;
      const request = purgeExpiredTripCaches()
        .then(() => syncAllTrips())
        .then(() => queryClient.invalidateQueries())
        .finally(() => {
          if (running.current === request) running.current = null;
        });
      running.current = request;
    };
    refresh();
    const network = NetInfo.addEventListener((state) => {
      if (state.isConnected && state.isInternetReachable !== false) refresh();
    });
    const appState = AppState.addEventListener('change', (state) => {
      if (state === 'active') refresh();
    });
    return () => {
      network();
      appState.remove();
    };
  }, [demoMode, queryClient, session]);

  return null;
}

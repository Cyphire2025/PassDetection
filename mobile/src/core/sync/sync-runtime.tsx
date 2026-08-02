import NetInfo from '@react-native-community/netinfo';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { AppState } from 'react-native';

import { useSessionStore } from '@/core/auth/session-store';
import { isDemoMode } from '@/core/demo/demo-mode';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

import { installAccessDeniedPurge, purgeExpiredTripCaches, subscribeTripPurges } from './access-cache';
import { registerBackgroundSync, unregisterBackgroundSync } from './background-sync';
import { syncAllTrips, syncTrip } from './sync-service';

const FOREGROUND_SYNC_INTERVAL_MS = 15_000;
const FULL_REFRESH_EVERY_TICKS = 4;

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
    let isActive = AppState.currentState === 'active';
    let isOnline = true;
    let tick = 0;
    const refresh = (full = true) => {
      if (running.current) return;
      if (!isActive || !isOnline) return;
      const selectedTripId = useSelectedTripStore.getState().tripId;
      const synchronize = () => full || !selectedTripId
        ? syncAllTrips()
        : syncTrip(selectedTripId).then((result) => [result]);
      const request = purgeExpiredTripCaches()
        .then(synchronize)
        .then(() => queryClient.invalidateQueries())
        .finally(() => {
          if (running.current === request) running.current = null;
        });
      running.current = request;
    };
    refresh();
    const network = NetInfo.addEventListener((state) => {
      isOnline = Boolean(state.isConnected && state.isInternetReachable !== false);
      if (isOnline) refresh();
    });
    const appState = AppState.addEventListener('change', (state) => {
      isActive = state === 'active';
      if (isActive) refresh();
    });
    const foreground = setInterval(() => {
      tick += 1;
      refresh(tick % FULL_REFRESH_EVERY_TICKS === 0);
    }, FOREGROUND_SYNC_INTERVAL_MS);
    return () => {
      network();
      appState.remove();
      clearInterval(foreground);
    };
  }, [demoMode, queryClient, session]);

  return null;
}

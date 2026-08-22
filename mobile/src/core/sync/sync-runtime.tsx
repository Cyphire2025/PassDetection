import { onlineManager, useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { AppState } from 'react-native';

import { useSessionStore } from '@/core/auth/session-store';
import { isDemoMode } from '@/core/demo/demo-mode';
import { recordMobileMetric } from '@/core/observability/mobile-observability';
import { setAccountDatabaseApplicationState } from '@/core/storage/database';
import { recoverPendingVaultEvictions } from '@/features/content/data/content-repository';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

import {
  installAccessDeniedPurge,
  purgeExpiredTripCaches,
  retryPendingTripPurges,
  subscribeTripPurges,
} from './access-cache';
import { registerBackgroundSync, unregisterBackgroundSync } from './background-sync';
import { isRequiredPreparationActive } from './required-preparation-lease';
import { SELECTED_TRIP_FALLBACK_INTERVAL_MS } from './sync-runtime-policy';
import { requestSync } from './sync-trigger';

export function SyncRuntime() {
  const demoMode = isDemoMode();
  const sessionId = useSessionStore((state) => state.session?.sessionId ?? null);
  const queryClient = useQueryClient();

  useEffect(() => {
    if (demoMode || !sessionId) {
      setAccountDatabaseApplicationState(false);
      return;
    }
    const applyState = (state: string) => {
      const active = state === 'active';
      setAccountDatabaseApplicationState(active);
      if (active) void recoverPendingVaultEvictions().catch(() => undefined);
    };
    applyState(AppState.currentState);
    const subscription = AppState.addEventListener('change', applyState);
    return () => {
      subscription.remove();
      setAccountDatabaseApplicationState(false);
    };
  }, [demoMode, sessionId]);

  useEffect(() => (demoMode ? undefined : installAccessDeniedPurge()), [demoMode]);

  useEffect(() => {
    if (demoMode) return;
    return subscribeTripPurges((tripId) => {
      void queryClient.cancelQueries({ predicate: (query) => query.queryKey.includes(tripId) });
      queryClient.removeQueries({ predicate: (query) => query.queryKey.includes(tripId) });
      // The trips query reads SQLite only; this publishes the local purge and
      // cannot create an independent network reconciliation.
      void queryClient.invalidateQueries({
        queryKey: ['mobile-trips'],
        refetchType: 'active',
      });
    });
  }, [demoMode, queryClient]);

  useEffect(() => {
    if (demoMode || !sessionId) {
      void unregisterBackgroundSync().catch(() => undefined);
      return;
    }

    void registerBackgroundSync()
      .then((registered) => {
        recordMobileMetric('background_registration', 1, {
          outcome: registered ? 'success' : 'failure',
          trigger: 'foreground',
        });
      })
      .catch(() => {
        recordMobileMetric('background_registration', 1, {
          outcome: 'failure',
          trigger: 'foreground',
        });
      });
    let disposed = false;
    let isActive = AppState.currentState === 'active';
    let isOnline = onlineManager.isOnline();
    let expiryPurge: Promise<void> | null = null;

    const expireLocalAccess = (): Promise<void> => {
      if (disposed || !isActive) return Promise.resolve();
      if (expiryPurge) return expiryPurge;
      const operation = retryPendingTripPurges()
        .then(() => purgeExpiredTripCaches())
        .then(() => undefined)
        .finally(() => {
          if (expiryPurge === operation) expiryPurge = null;
        });
      expiryPurge = operation;
      return operation;
    };

    const requestAutomaticRefresh = (forceFull = false) => {
      if (
        disposed
        || !isActive
        || !isOnline
        || isRequiredPreparationActive(sessionId)
      ) return;
      const selectedTripId = useSelectedTripStore.getState().tripId;
      const trigger = forceFull
        ? { scope: 'full' as const, reason: 'runtime-forced' }
        : {
          scope: 'auto' as const,
          tripId: selectedTripId,
          reason: 'runtime-lifecycle',
        };
      void expireLocalAccess()
        .then(() => requestSync(trigger))
        .catch(() => undefined);
    };

    const network = onlineManager.subscribe((nextOnline) => {
      const becameOnline = nextOnline && !isOnline;
      isOnline = nextOnline;
      if (becameOnline) requestAutomaticRefresh(false);
    });
    const appState = AppState.addEventListener('change', (state) => {
      const becameActive = state === 'active' && !isActive;
      isActive = state === 'active';
      if (becameActive) requestAutomaticRefresh(false);
    });
    const selection = useSelectedTripStore.subscribe((next, previous) => {
      if (!next.tripId || next.tripId === previous.tripId || !isActive || !isOnline) return;
      void requestSync({
        scope: 'trip',
        tripId: next.tripId,
        reason: 'selected-trip-changed',
      }).catch(() => undefined);
    });
    const fallback = setInterval(() => {
      requestAutomaticRefresh(false);
    }, SELECTED_TRIP_FALLBACK_INTERVAL_MS);

    requestAutomaticRefresh(false);

    return () => {
      disposed = true;
      network();
      appState.remove();
      selection();
      clearInterval(fallback);
    };
  }, [demoMode, sessionId]);

  return null;
}

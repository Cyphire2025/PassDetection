import { onlineManager, useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { AppState } from 'react-native';

import { useSessionStore } from '@/core/auth/session-store';
import { isDemoMode } from '@/core/demo/demo-mode';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

import {
  installAccessDeniedPurge,
  purgeExpiredTripCaches,
  retryPendingTripPurges,
  subscribeTripPurges,
} from './access-cache';
import { registerBackgroundSync, unregisterBackgroundSync } from './background-sync';
import { isRequiredPreparationActive } from './required-preparation-lease';
import {
  SELECTED_TRIP_FALLBACK_INTERVAL_MS,
  changedSyncTripIds,
  mergeSyncScopes,
  queryKeyMatchesAnyTrip,
  resolveSyncScope,
  syncRuntimeTimestamp,
  type SyncScope,
} from './sync-runtime-policy';
import {
  syncAllTripsWithSummary,
  syncTrip,
  syncTripFailure,
  type SyncAllTripsSummary,
  type SyncResult,
} from './sync-service';

export function SyncRuntime() {
  const demoMode = isDemoMode();
  const sessionId = useSessionStore((state) => state.session?.sessionId ?? null);
  const queryClient = useQueryClient();

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
    if (demoMode || !sessionId) {
      void unregisterBackgroundSync().catch(() => undefined);
      return;
    }

    void registerBackgroundSync().catch(() => undefined);
    let disposed = false;
    let isActive = AppState.currentState === 'active';
    let isOnline = onlineManager.isOnline();
    let lastFullSyncAt: number | null = null;
    let running: Promise<void> | null = null;
    let runningScope: SyncScope = 'none';
    let runningSelectedTripId: string | null = null;
    let queuedScope: SyncScope = 'none';
    let expiryPurge: Promise<void> | null = null;

    const invalidateChangedResults = async (
      results: SyncResult[],
      tripsChanged: boolean,
      removedTripIds: string[],
    ) => {
      if (disposed) return;
      const changedTripIds = changedSyncTripIds(results);
      for (const tripId of removedTripIds) {
        await queryClient.cancelQueries({ predicate: (query) => query.queryKey.includes(tripId) });
        queryClient.removeQueries({ predicate: (query) => query.queryKey.includes(tripId) });
      }
      const requests: Promise<unknown>[] = [];
      if (changedTripIds.length > 0) {
        requests.push(queryClient.invalidateQueries({
          predicate: (query) => queryKeyMatchesAnyTrip(query.queryKey, changedTripIds),
        }));
      }
      if (tripsChanged || changedTripIds.length > 0) {
        requests.push(queryClient.invalidateQueries({ queryKey: ['mobile-trips'] }));
      }
      await Promise.all(requests);
    };

    const expireLocalAccess = (): Promise<void> => {
      if (disposed || !isActive) return Promise.resolve();
      if (expiryPurge) return expiryPurge;
      const request = retryPendingTripPurges()
        .then(() => purgeExpiredTripCaches())
        .then(() => undefined)
        .finally(() => {
          if (expiryPurge === request) expiryPurge = null;
        });
      expiryPurge = request;
      return request;
    };

    const execute = (scope: SyncScope, selectedTripId: string | null) => {
      if (disposed || !isActive || !isOnline || scope === 'none') return;
      if (running) {
        if (scope === 'selected' && runningScope === 'selected' && selectedTripId === runningSelectedTripId) {
          return;
        }
        if (runningScope !== 'full') queuedScope = mergeSyncScopes(queuedScope, scope);
        return;
      }

      runningScope = scope;
      runningSelectedTripId = scope === 'selected' ? selectedTripId : null;
      const synchronize = async (): Promise<SyncAllTripsSummary> => {
        if (scope === 'full') return syncAllTripsWithSummary();
        if (!selectedTripId) {
          return {
            results: [],
            failures: [],
            requestedTripCount: 0,
            tripsChanged: false,
            removedTripIds: [],
          };
        }
        try {
          return {
            results: [await syncTrip(selectedTripId)],
            failures: [],
            requestedTripCount: 1,
            tripsChanged: false,
            removedTripIds: [],
          };
        } catch (error) {
          return {
            results: [],
            failures: [syncTripFailure(selectedTripId, error)],
            requestedTripCount: 1,
            tripsChanged: false,
            removedTripIds: [],
          };
        }
      };
      const request = expireLocalAccess()
        .then(synchronize)
        .then(async (summary) => {
          // A partial/total failure remains eligible for the next full refresh;
          // do not suppress it for the normal full-sync interval.
          if (scope === 'full' && summary.failures.length === 0) {
            lastFullSyncAt = syncRuntimeTimestamp();
          }
          await invalidateChangedResults(
            summary.results,
            summary.tripsChanged,
            summary.removedTripIds,
          );
        })
        .catch(() => undefined)
        .finally(() => {
          if (running !== request) return;
          running = null;
          runningScope = 'none';
          runningSelectedTripId = null;
          if (disposed) return;
          const pending = queuedScope;
          queuedScope = 'none';
          if (pending !== 'none') requestRefresh(pending === 'full');
        });
      running = request;
    };

    const requestRefresh = (forceFull = false) => {
      if (
        disposed
        || !isActive
        || !isOnline
        || isRequiredPreparationActive(sessionId)
      ) return;
      const selectedTripId = useSelectedTripStore.getState().tripId;
      const scope = resolveSyncScope({
        forceFull,
        selectedTripId,
        lastFullSyncAt,
        now: syncRuntimeTimestamp(),
      });
      execute(scope, selectedTripId);
    };

    const network = onlineManager.subscribe((nextOnline) => {
      const becameOnline = nextOnline && !isOnline;
      isOnline = nextOnline;
      if (becameOnline) requestRefresh(false);
    });
    const appState = AppState.addEventListener('change', (state) => {
      const becameActive = state === 'active' && !isActive;
      isActive = state === 'active';
      if (becameActive) {
        void expireLocalAccess().catch(() => undefined);
        requestRefresh(false);
      }
    });
    const selection = useSelectedTripStore.subscribe((next, previous) => {
      if (next.tripId && next.tripId !== previous.tripId) requestRefresh(false);
    });
    const fallback = setInterval(() => {
      void expireLocalAccess().catch(() => undefined);
      requestRefresh(false);
    }, SELECTED_TRIP_FALLBACK_INTERVAL_MS);

    void expireLocalAccess().catch(() => undefined);
    requestRefresh(false);

    return () => {
      disposed = true;
      network();
      appState.remove();
      selection();
      clearInterval(fallback);
    };
  }, [demoMode, queryClient, sessionId]);

  return null;
}

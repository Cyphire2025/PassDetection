import { useSessionStore } from '@/core/auth/session-store';
import { mobileQueryClient } from '@/core/query/query-client';
import { preloadPassengerTrip } from '@/features/content/data/passenger-preload';
import { preloadManagerTrips } from '@/features/content/data/manager-preload';
import { preloadCoordinatorTrips } from '@/features/coordinator/data/coordinator-preload';
import { localTrips, refreshTripsInContext } from '@/features/trips/data/trip-repository';
import { isDemoMode } from '@/core/demo/demo-mode';
import { isDemoPrincipal } from '@/core/demo/demo-data';
import type { Trip } from '@/features/trips/model/trip';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

import { completeRequiredPreparation } from './required-preparation-lease';
import { assertSyncContextActive, captureSyncContext } from './sync-context';
import { scheduleRemainingWorkspacePreparation } from './workspace-background-preload';

export type RequiredPreloadProgress = {
  percent: number;
  message: string;
  completedLabel: string;
};

export type RequiredPreloadResult = {
  destination:
    | '/(passenger)/select-trip'
    | '/(passenger)/(tabs)/trip'
    | '/(manager)/(tabs)/groups'
    | '/(coordinator)/(tabs)/groups';
};

function priorityTripFirst(trips: readonly Trip[]): Trip[] {
  const selectedTripId = useSelectedTripStore.getState().tripId;
  if (!selectedTripId) return [...trips];
  const selected = trips.find((trip) => trip.id === selectedTripId);
  if (!selected) return [...trips];
  return [selected, ...trips.filter((trip) => trip.id !== selectedTripId)];
}

export async function preloadAuthenticatedWorkspace(
  onProgress: (progress: RequiredPreloadProgress) => void,
): Promise<RequiredPreloadResult> {
  const session = useSessionStore.getState().session;
  if (!session) throw new Error('Authentication is required before preparing offline access.');
  if (isDemoMode() && isDemoPrincipal(session.principal)) {
    const trips = await localTrips();
    if (!trips.length) throw new Error('The sample workspace could not be loaded. Sign in again to reset it.');
    if (session.principal.principalType === 'passenger') useSelectedTripStore.getState().selectTrip(trips[0]!.id);
    completeRequiredPreparation(session.sessionId);
    onProgress({ percent: 100, message: 'Your sample workspace is ready', completedLabel: 'All sample information is stored on this device' });
    return { destination: session.principal.principalType === 'passenger' ? '/(passenger)/(tabs)/trip'
      : session.principal.principalType === 'client_manager' ? '/(manager)/(tabs)/groups' : '/(coordinator)/(tabs)/groups' };
  }

  // The signed login/refresh response already contains the authoritative
  // principal and has been committed to the account namespace before this
  // screen is reached. A second blocking `/mobile/me` request here previously
  // duplicated network work and could dead-end an otherwise valid login at 4%.
  // Trip/resource authorization below still revalidates the session server-side.
  onProgress({ percent: 4, message: 'Preparing your workspace', completedLabel: 'Secure session ready' });

  if (session.principal.principalType === 'passenger') {
    const result = await preloadPassengerTrip(onProgress);
    if (!result.selectionRequired) completeRequiredPreparation(session.sessionId);
    return {
      destination: result.selectionRequired
        ? '/(passenger)/select-trip'
        : '/(passenger)/(tabs)/trip',
    };
  }

  const lease = captureSyncContext();
  try {
    const { context: syncContext } = lease;
    assertSyncContextActive(syncContext);
    onProgress({ percent: 12, message: 'Loading assigned groups', completedLabel: 'Checking group access' });
    const result = await refreshTripsInContext(syncContext);
    assertSyncContextActive(syncContext);
    mobileQueryClient.setQueryData(['mobile-trips', syncContext.namespace], result);

    // The server/local trip repository returns a stable operational order. An
    // already-selected assigned trip takes precedence; otherwise only the
    // first available/upcoming trip is required before entering the workspace.
    const [priorityTrip, ...remainingTrips] = priorityTripFirst(result.trips);
    const requiredTrips = priorityTrip ? [priorityTrip] : [];

    if (session.principal.principalType === 'client_manager') {
      await preloadManagerTrips(requiredTrips, ({ progress, label }) => {
        onProgress({
          percent: 18 + Math.round(progress * 82),
          message: label,
          completedLabel: 'Preparing the first group; remaining groups will continue in the background',
        });
      }, syncContext);
      assertSyncContextActive(syncContext);
      completeRequiredPreparation(session.sessionId);
      void scheduleRemainingWorkspacePreparation('client_manager', remainingTrips)
        .catch(() => undefined);
      return { destination: '/(manager)/(tabs)/groups' };
    }

    await preloadCoordinatorTrips(requiredTrips, ({ progress, label }) => {
      onProgress({
        percent: 18 + Math.round(progress * 82),
        message: label,
        completedLabel: 'Preparing the first trip; remaining trips will continue in the background',
      });
    }, syncContext);
    assertSyncContextActive(syncContext);
    completeRequiredPreparation(session.sessionId);
    void scheduleRemainingWorkspacePreparation('coordinator', remainingTrips)
      .catch(() => undefined);
    return { destination: '/(coordinator)/(tabs)/groups' };
  } finally {
    lease.release();
  }
}

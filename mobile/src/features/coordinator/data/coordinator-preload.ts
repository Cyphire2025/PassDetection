import { canDeferWorkspacePreparationFailure } from '@/core/sync/preload-failure-policy';
import { scheduleTripDocumentHydration } from '@/core/sync/sync-service';
import {
  assertSyncContextActive,
  type ImmutableSyncContext,
} from '@/core/sync/sync-context';
import { requestSync } from '@/core/sync/sync-trigger';
import type { Trip } from '@/features/trips/model/trip';

import { refreshAttendanceSessions } from './attendance-sessions';

export type CoordinatorPreloadProgress = {
  progress: number;
  label: string;
};

type ProgressListener = (progress: CoordinatorPreloadProgress) => void;

export async function preloadCoordinatorTrip(
  trip: Trip,
  onProgress: ProgressListener,
  syncContext?: ImmutableSyncContext,
): Promise<{ failedDownloads: number }> {
  if (syncContext) assertSyncContextActive(syncContext);
  onProgress({ progress: 0.05, label: `Preparing ${trip.name}` });
  try {
    await requestSync(
      { scope: 'trip', tripId: trip.id, reason: 'coordinator-preload' },
      syncContext ? { signal: syncContext.signal } : {},
    );
  } catch (error) {
    if (syncContext) assertSyncContextActive(syncContext);
    if (!canDeferWorkspacePreparationFailure(error)) throw error;
    scheduleTripDocumentHydration(trip.id);
  }

  if (syncContext) assertSyncContextActive(syncContext);
  onProgress({ progress: 0.82, label: 'Saving attendance and passenger operations' });
  // refreshAttendanceSessions already falls back to a verified local activity
  // list. Reaching this catch would therefore mean neither server nor cached
  // attendance prerequisites are available and must not be presented as ready.
  await refreshAttendanceSessions(trip.id, syncContext);

  if (syncContext) assertSyncContextActive(syncContext);
  onProgress({
    progress: 1,
    label: `${trip.name} is prepared; select an attendance activity before scanning`,
  });
  return { failedDownloads: 0 };
}

export async function preloadCoordinatorTrips(
  trips: Trip[],
  onProgress: ProgressListener,
  syncContext?: ImmutableSyncContext,
): Promise<{ failedDownloads: number }> {
  if (syncContext) assertSyncContextActive(syncContext);
  if (trips.length === 0) {
    onProgress({ progress: 1, label: 'No assigned groups require preparation' });
    return { failedDownloads: 0 };
  }
  let failedDownloads = 0;
  let nextTripIndex = 0;
  const progressByTrip = trips.map(() => 0);
  const worker = async () => {
    while (nextTripIndex < trips.length) {
      const index = nextTripIndex;
      nextTripIndex += 1;
      const trip = trips[index];
      if (!trip) continue;
      if (syncContext) assertSyncContextActive(syncContext);
      const result = await preloadCoordinatorTrip(trip, ({ progress, label }) => {
        progressByTrip[index] = Math.max(progressByTrip[index] ?? 0, progress);
        onProgress({
          progress: progressByTrip.reduce((total, value) => total + value, 0) / trips.length,
          label,
        });
      }, syncContext);
      failedDownloads += result.failedDownloads;
    }
  };
  await Promise.all(Array.from({ length: Math.min(2, trips.length) }, () => worker()));
  if (syncContext) assertSyncContextActive(syncContext);
  return { failedDownloads };
}

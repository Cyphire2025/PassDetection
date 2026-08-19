import { canDeferWorkspacePreparationFailure } from '@/core/sync/preload-failure-policy';
import { scheduleTripDocumentHydration } from '@/core/sync/sync-service';
import {
  assertSyncContextActive,
  type ImmutableSyncContext,
} from '@/core/sync/sync-context';
import { requestSync } from '@/core/sync/sync-trigger';
import type { Trip } from '@/features/trips/model/trip';

export type ManagerPreloadProgress = {
  progress: number;
  label: string;
};

type ProgressListener = (progress: ManagerPreloadProgress) => void;

export async function preloadManagerTrip(
  trip: Trip,
  onProgress: ProgressListener,
  syncContext?: ImmutableSyncContext,
): Promise<{ failedDownloads: number }> {
  if (syncContext) assertSyncContextActive(syncContext);
  onProgress({ progress: 0.05, label: `Preparing ${trip.name}` });
  try {
    await requestSync(
      { scope: 'trip', tripId: trip.id, reason: 'manager-preload' },
      syncContext ? { signal: syncContext.signal } : {},
    );
  } catch (error) {
    if (syncContext) assertSyncContextActive(syncContext);
    if (!canDeferWorkspacePreparationFailure(error)) throw error;
    scheduleTripDocumentHydration(trip.id);
  }
  if (syncContext) assertSyncContextActive(syncContext);
  onProgress({ progress: 0.82, label: 'Saving readiness and group updates' });
  onProgress({
    progress: 1,
    label: `${trip.name} is ready; documents are being secured offline in the background`,
  });
  return { failedDownloads: 0 };
}

export async function preloadManagerTrips(
  trips: Trip[],
  onProgress: ProgressListener,
  syncContext?: ImmutableSyncContext,
): Promise<{ failedDownloads: number }> {
  if (syncContext) assertSyncContextActive(syncContext);
  if (!trips.length) {
    onProgress({ progress: 1, label: 'No assigned groups require preparation' });
    return { failedDownloads: 0 };
  }

  let nextTripIndex = 0;
  const progressByTrip = trips.map(() => 0);
  const report = (tripIndex: number, progress: number, label: string) => {
    progressByTrip[tripIndex] = Math.max(progressByTrip[tripIndex] ?? 0, progress);
    onProgress({
      progress: progressByTrip.reduce((total, value) => total + value, 0) / trips.length,
      label,
    });
  };
  const worker = async () => {
    while (nextTripIndex < trips.length) {
      const tripIndex = nextTripIndex;
      nextTripIndex += 1;
      const trip = trips[tripIndex];
      if (!trip) continue;
      if (syncContext) assertSyncContextActive(syncContext);
      await preloadManagerTrip(trip, ({ progress, label }) => {
        report(tripIndex, progress, label);
      }, syncContext);
    }
  };
  await Promise.all(Array.from({ length: Math.min(2, trips.length) }, () => worker()));
  if (syncContext) assertSyncContextActive(syncContext);
  return { failedDownloads: 0 };
}

import { syncTrip } from '@/core/sync/sync-service';
import {
  countMissingRequiredOfflineDocuments,
  prefetchCommonOfflineDocuments,
  prefetchRequiredCommonOfflineDocuments,
  REQUIRED_COMMON_DOCUMENT_SCOPES,
  type OfflinePrefetchProgress,
} from '@/features/content/data/content-repository';
import {
  documentPreloadStatus,
} from '@/features/content/data/preload-status';
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
): Promise<{ failedDownloads: number }> {
  onProgress({ progress: 0.05, label: `Preparing ${trip.name}` });
  const emptyPrefetch: OfflinePrefetchProgress = {
    total: 0,
    completed: 0,
    failed: 0,
    currentDocumentName: null,
  };
  const reportDocumentProgress = (progress: OfflinePrefetchProgress) => {
    const processed = progress.completed + progress.failed;
    const documentProgress = progress.total === 0 ? 1 : processed / progress.total;
    onProgress({
      progress: 0.15 + documentProgress * 0.6,
      label: progress.total === 0
        ? 'No published common documents to download'
        : `Preparing offline documents ${processed} of ${progress.total}`,
    });
  };
  let prefetch = emptyPrefetch;
  try {
    const result = await syncTrip(trip.id, { onDocumentProgress: reportDocumentProgress });
    prefetch = result.documentPrefetch ?? emptyPrefetch;
  } catch {
    // Reconcile any durable document jobs committed before a transient sync
    // failure. This is the only fallback prefetch; a successful sync already
    // performed the size-aware common-document pass.
    prefetch = await prefetchCommonOfflineDocuments(trip.id, reportDocumentProgress);
  }
  const requiredRetry = await prefetchRequiredCommonOfflineDocuments(
    trip.id,
    reportDocumentProgress,
  );
  if (requiredRetry.total > 0) prefetch = requiredRetry;
  const missingRequiredDocuments = await countMissingRequiredOfflineDocuments(
    trip.id,
    REQUIRED_COMMON_DOCUMENT_SCOPES,
  );
  if (requiredRetry.failed > 0 || missingRequiredDocuments > 0) {
    throw new Error(`Required documents for ${trip.name} could not be saved securely.`);
  }

  onProgress({ progress: 0.82, label: 'Saving attendance and passenger operations' });
  await refreshAttendanceSessions(trip.id).catch(() => null);

  const finalStatus = documentPreloadStatus(trip.name, prefetch);
  onProgress({
    progress: 1,
    label: prefetch.failed > 0
      ? `${finalStatus.message}; ${prefetch.failed} document${prefetch.failed === 1 ? '' : 's'} will retry later`
      : finalStatus.completedLabel,
  });
  return { failedDownloads: prefetch.failed };
}

export async function preloadCoordinatorTrips(
  trips: Trip[],
  onProgress: ProgressListener,
): Promise<{ failedDownloads: number }> {
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
      const result = await preloadCoordinatorTrip(trip, ({ progress, label }) => {
        progressByTrip[index] = Math.max(progressByTrip[index] ?? 0, progress);
        onProgress({
          progress: progressByTrip.reduce((total, value) => total + value, 0) / trips.length,
          label,
        });
      });
      failedDownloads += result.failedDownloads;
    }
  };
  await Promise.all(Array.from({ length: Math.min(2, trips.length) }, () => worker()));
  return { failedDownloads };
}

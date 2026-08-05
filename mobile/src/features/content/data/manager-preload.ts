import { syncTrip } from '@/core/sync/sync-service';
import type { Trip } from '@/features/trips/model/trip';

import {
  countMissingRequiredOfflineDocuments,
  prefetchCommonOfflineDocuments,
  prefetchRequiredCommonOfflineDocuments,
  REQUIRED_COMMON_DOCUMENT_SCOPES,
  type OfflinePrefetchProgress,
} from './content-repository';
import { documentPreloadStatus } from './preload-status';

export type ManagerPreloadProgress = {
  progress: number;
  label: string;
};

export async function preloadManagerTrips(
  trips: Trip[],
  onProgress: (progress: ManagerPreloadProgress) => void,
): Promise<{ failedDownloads: number }> {
  if (!trips.length) {
    onProgress({ progress: 1, label: 'No assigned groups require preparation' });
    return { failedDownloads: 0 };
  }

  let failedDownloads = 0;
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
      report(tripIndex, 0.05, `Preparing ${trip.name}`);
      const emptyPrefetch: OfflinePrefetchProgress = {
        total: 0,
        completed: 0,
        failed: 0,
        currentDocumentName: null,
      };
      const reportDocumentProgress = (progress: OfflinePrefetchProgress) => {
        const ratio = progress.total
          ? (progress.completed + progress.failed) / progress.total
          : 1;
        report(tripIndex, 0.6 + ratio * 0.4, progress.currentDocumentName
          ? `Securing ${progress.currentDocumentName}`
          : 'Securing common documents for offline use');
      };
      let prefetch = emptyPrefetch;
      try {
        const result = await syncTrip(trip.id, { onDocumentProgress: reportDocumentProgress });
        prefetch = result.documentPrefetch ?? emptyPrefetch;
      } catch {
        // A partial synchronization may already have committed usable common
        // document metadata. Reconcile its durable jobs once, then allow the
        // background runtime to retry the remote manifest later.
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
        throw new Error(
          'Required documents could not be saved for offline use. Check your connection and try again.',
        );
      }
      report(tripIndex, 0.45, 'Saving readiness and group updates');
      failedDownloads += prefetch.failed;
      const finalStatus = documentPreloadStatus(trip.name, prefetch);
      report(tripIndex, 1, prefetch.failed > 0
        ? `${finalStatus.message}; ${prefetch.failed} document${prefetch.failed === 1 ? '' : 's'} will retry later`
        : finalStatus.completedLabel);
    }
  };
  await Promise.all(Array.from({ length: Math.min(2, trips.length) }, () => worker()));
  return { failedDownloads };
}

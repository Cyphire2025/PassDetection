import { syncTrip } from '@/core/sync/sync-service';
import { refreshTrips } from '@/features/trips/data/trip-repository';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

import {
  loadQr,
  prefetchPassengerOfflineDocuments,
  refreshAnnouncements,
  refreshCommonDocuments,
  refreshDocuments,
} from './content-repository';

export type PassengerPreloadProgress = {
  percent: number;
  message: string;
  completedLabel: string;
};

export type PassengerPreloadResult = {
  tripId: string;
  failedDownloads: number;
};

export async function preloadPassengerTrip(
  onProgress: (progress: PassengerPreloadProgress) => void,
): Promise<PassengerPreloadResult> {
  onProgress({ percent: 8, message: 'Finding your available trip', completedLabel: 'Loading trip access' });
  const tripResult = await refreshTrips();
  const selectedTripId = useSelectedTripStore.getState().tripId;
  const trip = tripResult.trips.find((item) => item.id === selectedTripId) ?? tripResult.trips[0];
  if (!trip) throw new Error('No eligible trip is currently available for this passenger account.');
  useSelectedTripStore.getState().selectTrip(trip.id);

  onProgress({ percent: 25, message: 'Downloading trip information', completedLabel: trip.name });
  const resources = await Promise.allSettled([
    refreshAnnouncements(trip.id),
    refreshCommonDocuments(trip.id),
    refreshDocuments(trip.id),
    loadQr(trip.id),
  ]);
  const failedResource = resources.find((resource) => resource.status === 'rejected');
  if (failedResource?.status === 'rejected') {
    throw new Error(
      failedResource.reason instanceof Error
        ? failedResource.reason.message
        : 'Required trip information is not available online or in the encrypted offline cache.',
    );
  }

  let latestCompleted = 0;
  let latestTotal = 0;
  const prefetch = await prefetchPassengerOfflineDocuments(trip.id, (progress) => {
    latestCompleted = progress.completed;
    latestTotal = progress.total;
    const documentRatio = progress.total ? (progress.completed + progress.failed) / progress.total : 1;
    onProgress({
      percent: 42 + Math.round(documentRatio * 46),
      message: progress.currentDocumentName
        ? `Securing ${progress.currentDocumentName} for offline use`
        : 'Securing your documents for offline use',
      completedLabel: progress.total
        ? `${progress.completed + progress.failed} of ${progress.total} documents processed`
        : 'No new files to download',
    });
  });
  if (prefetch.failed) {
    throw new Error(`${prefetch.failed} required document${prefetch.failed === 1 ? '' : 's'} could not be saved offline. Check storage and connection, then try again.`);
  }

  onProgress({
    percent: 92,
    message: 'Checking for the latest trip updates',
    completedLabel: latestTotal ? `${latestCompleted} documents ready offline` : 'Offline metadata ready',
  });
  await syncTrip(trip.id).catch(() => null);
  onProgress({
    percent: 100,
    message: 'Your trip is ready',
    completedLabel: 'Required documents are ready offline',
  });
  return { tripId: trip.id, failedDownloads: prefetch.failed };
}

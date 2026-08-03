import { ApiError } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';
import { mobileQueryClient } from '@/core/query/query-client';
import { OfflineDatabaseIntegrityError } from '@/core/storage/database';
import { syncTrip } from '@/core/sync/sync-service';
import { isSyncContextChanged } from '@/core/sync/sync-context';
import {
  passengerTripForRequiredPreload,
  rememberPassengerTrip,
  rememberedPassengerTrip,
} from '@/features/trips/data/passenger-trip-selection';
import { refreshTrips } from '@/features/trips/data/trip-repository';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

import {
  countMissingRequiredOfflineDocuments,
  prefetchPassengerOfflineDocuments,
  prefetchRequiredPassengerOfflineDocuments,
  REQUIRED_PASSENGER_DOCUMENT_SCOPES,
  type OfflinePrefetchProgress,
} from './content-repository';
import { documentPreloadStatus } from './preload-status';

export type PassengerPreloadProgress = {
  percent: number;
  message: string;
  completedLabel: string;
};

export type PassengerPreloadResult = {
  tripId: string | null;
  failedDownloads: number;
  selectionRequired: boolean;
};

export async function preloadPassengerTrip(
  onProgress: (progress: PassengerPreloadProgress) => void,
  requestedTripId?: string,
): Promise<PassengerPreloadResult> {
  onProgress({ percent: 8, message: 'Finding your available trip', completedLabel: 'Loading trip access' });
  const tripResult = await refreshTrips();
  const principal = useSessionStore.getState().session?.principal;
  if (principal) {
    const accountKey = principalAccountNamespace(principal);
    mobileQueryClient.setQueryData(['mobile-trips', accountKey], tripResult);
  }
  if (!tripResult.trips.length) {
    throw new Error('No eligible trip is currently available for this passenger account.');
  }
  const trip = passengerTripForRequiredPreload(tripResult.trips, requestedTripId);
  if (requestedTripId && !trip) {
    throw new Error('This trip is no longer assigned to the current passenger account.');
  }
  if (!trip) {
    const remembered = await rememberedPassengerTrip(tripResult.trips);
    if (remembered) useSelectedTripStore.getState().selectTrip(remembered.id);
    onProgress({
      percent: 100,
      message: 'Choose the trip you want to open',
      completedLabel: `${tripResult.trips.length} trips available`,
    });
    return { tripId: null, failedDownloads: 0, selectionRequired: true };
  }
  await rememberPassengerTrip(tripResult.trips, trip.id);
  useSelectedTripStore.getState().selectTrip(trip.id);

  onProgress({ percent: 25, message: 'Synchronizing trip information', completedLabel: trip.name });
  let synchronizationDeferred = false;
  const emptyPrefetch: OfflinePrefetchProgress = {
    total: 0,
    completed: 0,
    failed: 0,
    currentDocumentName: null,
  };
  const reportDocumentProgress = (progress: OfflinePrefetchProgress) => {
    const processed = progress.completed + progress.failed;
    const documentRatio = progress.total ? processed / progress.total : 1;
    onProgress({
      percent: 42 + Math.round(documentRatio * 46),
      message: progress.currentDocumentName
        ? `Securing ${progress.currentDocumentName} for offline use`
        : 'Securing your documents for offline use',
      completedLabel: progress.total
        ? `${processed} of ${progress.total} documents processed`
        : 'No new files to download',
    });
  };
  let prefetch = emptyPrefetch;
  try {
    const result = await syncTrip(trip.id, { onDocumentProgress: reportDocumentProgress });
    prefetch = result.documentPrefetch ?? emptyPrefetch;
  } catch (error) {
    if (
      error instanceof OfflineDatabaseIntegrityError ||
      isSyncContextChanged(error) ||
      (error instanceof ApiError && (error.status === 401 || error.status === 403))
    ) {
      throw error;
    }
    synchronizationDeferred = true;
    // A partial sync may already have committed usable metadata. Secure those
    // local files now, then let the event-driven runtime retry remote changes.
    prefetch = await prefetchPassengerOfflineDocuments(trip.id, reportDocumentProgress);
  }
  // A foreground launch is an explicit retry boundary. Retry deferred jobs now
  // and do not enter the workspace while a newly published required file is
  // still absent from encrypted local storage.
  const requiredRetry = await prefetchRequiredPassengerOfflineDocuments(
    trip.id,
    reportDocumentProgress,
  );
  if (requiredRetry.total > 0) prefetch = requiredRetry;
  const missingRequiredDocuments = await countMissingRequiredOfflineDocuments(
    trip.id,
    REQUIRED_PASSENGER_DOCUMENT_SCOPES,
  );
  if (requiredRetry.failed > 0 || missingRequiredDocuments > 0) {
    throw new Error(
      'Required documents could not be saved securely. Check your connection and try again.',
    );
  }
  onProgress({
    percent: 92,
    message: 'Checking for the latest trip updates',
    completedLabel: prefetch.total
      ? `${prefetch.completed} documents ready offline`
      : 'Offline metadata ready',
  });
  const finalStatus = documentPreloadStatus('Your trip', prefetch);
  onProgress({
    percent: 100,
    message: synchronizationDeferred ? 'Your trip is available' : finalStatus.message,
    completedLabel: synchronizationDeferred
      ? `${finalStatus.completedLabel}; latest updates will retry in the background`
      : finalStatus.completedLabel,
  });
  return {
    tripId: trip.id,
    failedDownloads: prefetch.failed,
    selectionRequired: false,
  };
}

import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';
import { mobileQueryClient } from '@/core/query/query-client';
import { canDeferWorkspacePreparationFailure } from '@/core/sync/preload-failure-policy';
import { scheduleTripDocumentHydration } from '@/core/sync/sync-service';
import { requestSync } from '@/core/sync/sync-trigger';
import {
  passengerTripForRequiredPreload,
  rememberPassengerTrip,
  rememberedPassengerTrip,
} from '@/features/trips/data/passenger-trip-selection';
import { refreshTrips } from '@/features/trips/data/trip-repository';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

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
  try {
    // Metadata and authorization state form the shell boundary. Potentially
    // large document bytes use the account-scoped background lane so a valid
    // cached workspace is never held behind downloads.
    await requestSync({
      scope: 'trip',
      tripId: trip.id,
      reason: 'passenger-preload',
    });
  } catch (error) {
    if (!canDeferWorkspacePreparationFailure(error)) throw error;
    synchronizationDeferred = true;
    // A partial sync may already have committed usable metadata and durable
    // document jobs. Start that bounded lane now; the runtime retries both
    // metadata and bytes on the next online/active trigger.
    scheduleTripDocumentHydration(trip.id);
  }
  onProgress({
    percent: 92,
    message: 'Checking for the latest trip updates',
    completedLabel: 'Offline metadata ready',
  });
  onProgress({
    percent: 100,
    message: synchronizationDeferred ? 'Your trip is available' : 'Your trip is ready',
    completedLabel: synchronizationDeferred
      ? 'Cached information is ready; latest updates and documents will retry in the background'
      : 'Documents are being secured for offline use in the background',
  });
  return {
    tripId: trip.id,
    // Background outcomes remain represented by durable jobs and the Documents
    // screen; returning an invented synchronous failure count would be stale.
    failedDownloads: 0,
    selectionRequired: false,
  };
}

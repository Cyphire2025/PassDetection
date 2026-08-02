import { syncTrip } from '@/core/sync/sync-service';
import {
  cacheDocument,
  refreshCommonDocuments,
  type DocumentWithOfflineState,
} from '@/features/content/data/content-repository';
import type { Trip } from '@/features/trips/model/trip';

import { refreshAttendanceSessions } from './attendance-sessions';

export type CoordinatorPreloadProgress = {
  progress: number;
  label: string;
};

type ProgressListener = (progress: CoordinatorPreloadProgress) => void;

async function cacheDocumentsBounded(
  documents: DocumentWithOfflineState[],
  onProgress: (completed: number, total: number) => void,
): Promise<void> {
  const required = documents.filter(
    (document) => document.offline_available && document.metadata_state === 'ready',
  );
  if (required.length === 0) {
    onProgress(0, 0);
    return;
  }

  let cursor = 0;
  let completed = 0;
  const worker = async () => {
    while (cursor < required.length) {
      const index = cursor;
      cursor += 1;
      const document = required[index];
      if (!document) continue;
      await cacheDocument(document);
      completed += 1;
      onProgress(completed, required.length);
    }
  };
  await Promise.all(Array.from({ length: Math.min(3, required.length) }, () => worker()));
}

export async function preloadCoordinatorTrip(
  trip: Trip,
  onProgress: ProgressListener,
): Promise<void> {
  onProgress({ progress: 0.05, label: `Preparing ${trip.name}` });
  await syncTrip(trip.id);

  onProgress({ progress: 0.55, label: 'Saving attendance and passenger operations' });
  await refreshAttendanceSessions(trip.id);

  onProgress({ progress: 0.7, label: 'Downloading required common documents' });
  const documents = await refreshCommonDocuments(trip.id);
  await cacheDocumentsBounded(documents.items, (completed, total) => {
    const documentProgress = total === 0 ? 1 : completed / total;
    onProgress({
      progress: 0.7 + documentProgress * 0.3,
      label: total === 0
        ? 'No published common documents to download'
        : `Downloading required documents ${completed} of ${total}`,
    });
  });
  onProgress({ progress: 1, label: `${trip.name} is ready offline` });
}

export async function preloadCoordinatorTrips(
  trips: Trip[],
  onProgress: ProgressListener,
): Promise<void> {
  if (trips.length === 0) {
    onProgress({ progress: 1, label: 'No assigned groups require preparation' });
    return;
  }
  for (let index = 0; index < trips.length; index += 1) {
    const trip = trips[index];
    if (!trip) continue;
    await preloadCoordinatorTrip(trip, ({ progress, label }) => {
      onProgress({ progress: (index + progress) / trips.length, label });
    });
  }
}

import { syncTrip } from '@/core/sync/sync-service';
import type { Trip } from '@/features/trips/model/trip';

import {
  loadReadiness,
  prefetchCommonOfflineDocuments,
  refreshAnnouncements,
  refreshCommonDocuments,
} from './content-repository';

export type ManagerPreloadProgress = {
  progress: number;
  label: string;
};

export async function preloadManagerTrips(
  trips: Trip[],
  onProgress: (progress: ManagerPreloadProgress) => void,
): Promise<void> {
  if (!trips.length) {
    onProgress({ progress: 1, label: 'No assigned groups require preparation' });
    return;
  }

  for (let tripIndex = 0; tripIndex < trips.length; tripIndex += 1) {
    const trip = trips[tripIndex];
    if (!trip) continue;
    const report = (progress: number, label: string) => {
      onProgress({ progress: (tripIndex + progress) / trips.length, label });
    };
    report(0.05, `Preparing ${trip.name}`);
    await syncTrip(trip.id).catch(() => null);
    report(0.45, 'Saving readiness and group updates');
    await Promise.all([
      refreshAnnouncements(trip.id),
      refreshCommonDocuments(trip.id),
      loadReadiness(trip.id),
    ]);
    const prefetch = await prefetchCommonOfflineDocuments(trip.id, (progress) => {
      const ratio = progress.total ? (progress.completed + progress.failed) / progress.total : 1;
      report(0.6 + ratio * 0.4, progress.currentDocumentName
        ? `Securing ${progress.currentDocumentName}`
        : 'Securing common documents for offline use');
    });
    if (prefetch.failed) {
      throw new Error(`${prefetch.failed} required group document${prefetch.failed === 1 ? '' : 's'} could not be saved offline.`);
    }
    report(1, `${trip.name} is ready offline`);
  }
}

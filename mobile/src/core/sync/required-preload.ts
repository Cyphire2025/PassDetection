import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';
import { mobileQueryClient } from '@/core/query/query-client';
import { preloadPassengerTrip } from '@/features/content/data/passenger-preload';
import { preloadManagerTrips } from '@/features/content/data/manager-preload';
import { preloadCoordinatorTrips } from '@/features/coordinator/data/coordinator-preload';
import { refreshTrips } from '@/features/trips/data/trip-repository';

import { completeRequiredPreparation } from './required-preparation-lease';

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

export async function preloadAuthenticatedWorkspace(
  onProgress: (progress: RequiredPreloadProgress) => void,
): Promise<RequiredPreloadResult> {
  const session = useSessionStore.getState().session;
  if (!session) throw new Error('Authentication is required before preparing offline access.');

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

  onProgress({ percent: 12, message: 'Loading assigned groups', completedLabel: 'Checking group access' });
  const result = await refreshTrips();
  const accountKey = principalAccountNamespace(session.principal);
  mobileQueryClient.setQueryData(['mobile-trips', accountKey], result);
  if (session.principal.principalType === 'client_manager') {
    const managerPreload = await preloadManagerTrips(result.trips, ({ progress, label }) => {
      onProgress({
        percent: 18 + Math.round(progress * 82),
        message: label,
        completedLabel: 'Preparing group summaries and documents',
      });
    });
    if (managerPreload.failedDownloads > 0) {
      onProgress({
        percent: 100,
        message: 'Assigned groups are available',
        completedLabel: `${managerPreload.failedDownloads} document${managerPreload.failedDownloads === 1 ? '' : 's'} will retry later`,
      });
    }
    completeRequiredPreparation(session.sessionId);
    return { destination: '/(manager)/(tabs)/groups' };
  }

  const coordinatorPreload = await preloadCoordinatorTrips(result.trips, ({ progress, label }) => {
    onProgress({
      percent: 18 + Math.round(progress * 82),
      message: label,
      completedLabel: 'Preparing offline trip operations',
    });
  });
  if (coordinatorPreload.failedDownloads > 0) {
    onProgress({
      percent: 100,
      message: 'Assigned trips are available',
      completedLabel: `${coordinatorPreload.failedDownloads} document${coordinatorPreload.failedDownloads === 1 ? '' : 's'} will retry later`,
    });
  }
  completeRequiredPreparation(session.sessionId);
  return { destination: '/(coordinator)/(tabs)/groups' };
}

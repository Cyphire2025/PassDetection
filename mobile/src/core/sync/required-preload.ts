import { refreshSessionPrincipal } from '@/core/auth/session-service';
import { useSessionStore } from '@/core/auth/session-store';
import { preloadPassengerTrip } from '@/features/content/data/passenger-preload';
import { preloadManagerTrips } from '@/features/content/data/manager-preload';
import { preloadCoordinatorTrips } from '@/features/coordinator/data/coordinator-preload';
import { refreshTrips } from '@/features/trips/data/trip-repository';

export type RequiredPreloadProgress = {
  percent: number;
  message: string;
  completedLabel: string;
};

export type RequiredPreloadResult = {
  destination: '/(passenger)/(tabs)/trip' | '/(manager)/(tabs)/groups' | '/(coordinator)/(tabs)/groups';
};

export async function preloadAuthenticatedWorkspace(
  onProgress: (progress: RequiredPreloadProgress) => void,
): Promise<RequiredPreloadResult> {
  const session = useSessionStore.getState().session;
  if (!session) throw new Error('Authentication is required before preparing offline access.');

  onProgress({ percent: 4, message: 'Confirming your account', completedLabel: 'Checking secure session' });
  await refreshSessionPrincipal();

  if (session.principal.principalType === 'passenger') {
    await preloadPassengerTrip(onProgress);
    return { destination: '/(passenger)/(tabs)/trip' };
  }

  onProgress({ percent: 12, message: 'Loading assigned groups', completedLabel: 'Checking group access' });
  const result = await refreshTrips();
  if (session.principal.principalType === 'client_manager') {
    await preloadManagerTrips(result.trips, ({ progress, label }) => {
      onProgress({
        percent: 18 + Math.round(progress * 82),
        message: label,
        completedLabel: 'Preparing group summaries and documents',
      });
    });
    return { destination: '/(manager)/(tabs)/groups' };
  }

  await preloadCoordinatorTrips(result.trips, ({ progress, label }) => {
    onProgress({
      percent: 18 + Math.round(progress * 82),
      message: label,
      completedLabel: 'Preparing offline trip operations',
    });
  });
  return { destination: '/(coordinator)/(tabs)/groups' };
}

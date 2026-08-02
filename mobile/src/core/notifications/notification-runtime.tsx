import * as Notifications from 'expo-notifications';
import { useRouter } from 'expo-router';
import { useEffect } from 'react';

import { useSessionStore } from '@/core/auth/session-store';
import { isDemoMode } from '@/core/demo/demo-mode';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

import { notificationData, registerPushDevice, type NotificationData } from './notification-service';

export function NotificationRuntime() {
  const demoMode = isDemoMode();
  const router = useRouter();
  const session = useSessionStore((state) => state.session);

  useEffect(() => {
    if (!session || demoMode) return;
    void registerPushDevice().catch(() => undefined);
  }, [demoMode, session]);

  useEffect(() => {
    function open(data: NotificationData) {
      useSelectedTripStore.getState().selectTrip(data.trip_id);
      switch (session?.principal.principalType) {
        case 'passenger':
          router.push(data.route === 'documents' ? '/(passenger)/(tabs)/documents' : data.route === 'qr' ? '/(passenger)/(tabs)/qr' : data.route === 'updates' ? '/(passenger)/(tabs)/updates' : '/(passenger)/(tabs)/trip');
          break;
        case 'client_manager':
          router.push(data.route === 'readiness' ? '/(manager)/(tabs)/readiness' : data.route === 'updates' ? '/(manager)/(tabs)/updates' : data.route === 'trip' ? '/(manager)/(tabs)/itinerary' : '/(manager)/(tabs)/groups');
          break;
        case 'coordinator':
          router.push(data.route === 'attendance' ? '/(coordinator)/(tabs)/attendance' : data.route === 'passengers' ? '/(coordinator)/(tabs)/passengers' : data.route === 'updates' ? '/(coordinator)/operations/updates' : '/(coordinator)/(tabs)/groups');
          break;
      }
    }

    const subscription = Notifications.addNotificationResponseReceivedListener((response) => {
      const data = notificationData(response);
      if (data) open(data);
    });
    void Notifications.getLastNotificationResponseAsync().then((response) => {
      if (!response) return;
      const data = notificationData(response);
      if (data) open(data);
    });
    return () => subscription.remove();
  }, [router, session?.principal.principalType]);

  return null;
}

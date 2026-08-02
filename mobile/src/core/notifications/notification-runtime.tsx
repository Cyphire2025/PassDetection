import * as Notifications from 'expo-notifications';
import { useRouter } from 'expo-router';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';

import { useSessionStore } from '@/core/auth/session-store';
import { isDemoMode } from '@/core/demo/demo-mode';
import { syncTrip } from '@/core/sync/sync-service';
import { useCoordinatorTripStore } from '@/features/coordinator/state/coordinator-trip-store';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

import {
  notificationContentData,
  notificationData,
  registerPushDevice,
  type NotificationData,
} from './notification-service';

export function NotificationRuntime() {
  const demoMode = isDemoMode();
  const router = useRouter();
  const queryClient = useQueryClient();
  const session = useSessionStore((state) => state.session);
  const principalId = session?.principal.id ?? null;
  const principalType = session?.principal.principalType ?? null;

  useEffect(() => {
    if (!session || demoMode) return;
    void registerPushDevice().catch(() => undefined);
  }, [demoMode, session]);

  useEffect(() => {
    function open(data: NotificationData) {
      switch (principalType) {
        case 'passenger':
          useSelectedTripStore.getState().selectTrip(data.trip_id);
          router.push(data.route === 'documents' ? '/(passenger)/(tabs)/documents' : data.route === 'qr' ? '/(passenger)/(tabs)/qr' : data.route === 'updates' ? '/(passenger)/(tabs)/updates' : '/(passenger)/(tabs)/trip');
          break;
        case 'client_manager':
          useSelectedTripStore.getState().selectTrip(data.trip_id);
          router.push(data.route === 'readiness' ? '/(manager)/(tabs)/readiness' : data.route === 'updates' ? '/(manager)/(tabs)/updates' : data.route === 'trip' ? '/(manager)/(tabs)/itinerary' : '/(manager)/(tabs)/groups');
          break;
        case 'coordinator':
          if (!principalId) return;
          useCoordinatorTripStore.getState().selectTrip(principalId, data.trip_id);
          router.push(data.route === 'attendance' ? '/(coordinator)/(tabs)/attendance' : data.route === 'passengers' ? '/(coordinator)/(tabs)/passengers' : data.route === 'updates' ? '/(coordinator)/operations/updates' : '/(coordinator)/(tabs)/groups');
          break;
      }
    }

    const received = Notifications.addNotificationReceivedListener((notification) => {
      const data = notificationContentData(notification);
      if (!data || !principalId) return;
      void syncTrip(data.trip_id)
        .then(() => queryClient.invalidateQueries({
          predicate: (query) => query.queryKey.includes(data.trip_id),
        }))
        .catch(() => undefined);
    });

    const subscription = Notifications.addNotificationResponseReceivedListener((response) => {
      const data = notificationData(response);
      if (data) open(data);
    });
    void Notifications.getLastNotificationResponseAsync().then((response) => {
      if (!response) return;
      const data = notificationData(response);
      if (data) open(data);
    });
    return () => {
      received.remove();
      subscription.remove();
    };
  }, [principalId, principalType, queryClient, router]);

  return null;
}

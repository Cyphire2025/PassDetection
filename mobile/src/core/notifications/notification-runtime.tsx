import * as Notifications from 'expo-notifications';
import { useRouter } from 'expo-router';
import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef } from 'react';
import { AppState } from 'react-native';

import { useSessionStore } from '@/core/auth/session-store';
import { isDemoMode } from '@/core/demo/demo-mode';
import {
  getHandledNotificationResponse,
  setHandledNotificationResponse,
} from '@/core/storage/secure-store';
import { syncTrip } from '@/core/sync/sync-service';
import { useCoordinatorTripStore } from '@/features/coordinator/state/coordinator-trip-store';
import { localTrips, refreshTrips } from '@/features/trips/data/trip-repository';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

import { reconcileDepartureReminders } from './departure-reminders';
import {
  notificationContentData,
  notificationData,
  NotificationRegistrationError,
  registerPushDevice,
} from './notification-service';
import {
  isAssignedNotificationTrip,
  notificationAccountKey,
  notificationDestination,
  notificationResponseKey,
} from './notification-routing';

export function NotificationRuntime() {
  const demoMode = isDemoMode();
  const router = useRouter();
  const queryClient = useQueryClient();
  const session = useSessionStore((state) => state.session);
  const principalId = session?.principal.id ?? null;
  const accountId = session?.principal.accountId ?? null;
  const principalType = session?.principal.principalType ?? null;
  const agencyId = session?.principal.agencyId ?? null;
  const sessionId = session?.sessionId ?? null;
  const registrationInFlight = useRef<Promise<void> | null>(null);

  const registerNotifications = useCallback(() => {
    if (!sessionId || demoMode || registrationInFlight.current) return;
    const operation = registerPushDevice()
      .then((registered) => {
        if (!registered) console.warn('[notifications] permission not granted');
      })
      .catch((error: unknown) => {
        const code = error instanceof NotificationRegistrationError
          ? error.code
          : 'PUSH_REGISTRATION_FAILED';
        console.warn('[notifications] registration deferred', { code });
      })
      .then(async () => {
        const trips = await localTrips();
        await reconcileDepartureReminders(trips);
      })
      .catch(() => undefined)
      .finally(() => {
        if (registrationInFlight.current === operation) registrationInFlight.current = null;
      });
    registrationInFlight.current = operation;
  }, [demoMode, sessionId]);

  useEffect(() => {
    if (!sessionId || demoMode) return;
    registerNotifications();
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active') registerNotifications();
    });
    return () => subscription.remove();
  }, [demoMode, registerNotifications, sessionId]);

  useEffect(() => {
    if (!sessionId || !agencyId || !accountId || !principalId || !principalType) return;
    const expectedSessionId = sessionId;
    const expectedRole = principalType;
    const expectedPrincipal = {
      agencyId,
      accountId,
      id: principalId,
      principalType: expectedRole,
    };
    const accountKey = notificationAccountKey(expectedPrincipal);
    const handlingResponses = new Set<string>();

    const sessionStillActive = () => {
      const current = useSessionStore.getState().session;
      return current?.sessionId === expectedSessionId
        && current.principal.id === expectedPrincipal.id
        && current.principal.accountId === expectedPrincipal.accountId
        && current.principal.agencyId === expectedPrincipal.agencyId
        && current.principal.principalType === expectedPrincipal.principalType;
    };

    async function open(response: Notifications.NotificationResponse) {
      const data = notificationData(response);
      if (!data || !sessionStillActive()) return;
      const responseKey = notificationResponseKey(
        data,
        response.notification.request.identifier,
      );
      if (!responseKey || handlingResponses.has(responseKey)) return;
      if ((await getHandledNotificationResponse(accountKey)) === responseKey) return;
      handlingResponses.add(responseKey);
      try {
        const assignments = await refreshTrips();
        if (!sessionStillActive()) return;
        const assigned = isAssignedNotificationTrip(assignments.trips, data.trip_id);

        // Claim this response before navigation so Expo's persisted last response
        // cannot replay it on a later render or process restart. Storage failure is
        // non-fatal to the user journey; the in-memory claim still coalesces this run.
        await setHandledNotificationResponse(accountKey, responseKey).catch(() => undefined);
        if (!assigned) {
          if (expectedRole === 'coordinator') {
            useCoordinatorTripStore.getState().clearSelection(accountKey);
            router.push('/(coordinator)/(tabs)/groups');
          } else if (expectedRole === 'client_manager') {
            useSelectedTripStore.getState().clear();
            router.push('/(manager)/(tabs)/groups');
          } else {
            router.push('/(passenger)/select-trip');
          }
          return;
        }

        if (expectedRole === 'passenger') {
          router.push({
            pathname: '/(passenger)/select-trip',
            params: { tripId: data.trip_id, next: data.route },
          });
          return;
        }
        if (expectedRole === 'client_manager') {
          useSelectedTripStore.getState().selectTrip(data.trip_id);
        } else {
          // Coordinator selection is scoped by agency and principal. Passing only
          // the principal id allowed a cross-agency stale selection to be cleared
          // immediately by activateAccount(), breaking the deep link.
          useCoordinatorTripStore.getState().selectTrip(accountKey, data.trip_id);
        }
        router.push(notificationDestination(expectedRole, data.route));
      } catch {
        // Assignment validation is fail-closed. A network/cache failure never
        // navigates into an operational screen for an unverified trip.
      } finally {
        handlingResponses.delete(responseKey);
      }
    }

    const received = Notifications.addNotificationReceivedListener((notification) => {
      const data = notificationContentData(notification);
      if (!data || !principalId) return;
      void syncTrip(data.trip_id)
        .then((result) => {
          if (!result.changed) return undefined;
          return Promise.all([
            queryClient.invalidateQueries({
              predicate: (query) => query.queryKey.includes(data.trip_id),
            }),
            queryClient.invalidateQueries({ queryKey: ['mobile-trips'] }),
          ]);
        })
        .catch(() => undefined);
    });

    const subscription = Notifications.addNotificationResponseReceivedListener((response) => {
      void open(response);
    });
    void Notifications.getLastNotificationResponseAsync().then((response) => {
      if (!response) return;
      void open(response);
    });
    return () => {
      received.remove();
      subscription.remove();
    };
  }, [accountId, agencyId, principalId, principalType, queryClient, router, sessionId]);

  return null;
}

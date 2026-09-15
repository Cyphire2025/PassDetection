import * as Device from 'expo-device';
import * as Crypto from 'expo-crypto';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';
import { z } from 'zod';

import { apiRequest } from '@/core/api/client';
import {
  captureAuthenticationSnapshot,
  isAuthenticationSnapshotCurrent,
  useSessionStore,
} from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';
import {
  clearPushRegistrationMarker,
  getInstallationId,
  getPushRegistrationMarker,
  setPushRegistrationMarker,
} from '@/core/storage/secure-store';

import { usePushRegistrationState, type PushRegistrationStatus } from './notification-registration-state';
import { nativeNotificationProvider, NotificationRegistrationError, type NotificationProvider } from './native-push-provider';

export { configureTripUpdateChannel, fcmNotificationProvider, requestNotificationPermission, NotificationRegistrationError, type NotificationProvider } from './native-push-provider';

const PUSH_REGISTRATION_REFRESH_MS = 24 * 60 * 60_000;

export const NotificationDataSchema = z.object({
  route: z.enum(['trip', 'documents', 'qr', 'updates', 'readiness', 'attendance', 'passengers']),
  trip_id: z.string().uuid().optional(),
  event_id: z.string().uuid().optional(),
}).strict().refine((data) => Boolean(data.trip_id) || (data.route === 'updates' && Boolean(data.event_id)), {
  message: 'Only an identified Updates notification can open without a trip.',
});

export type NotificationData = z.infer<typeof NotificationDataSchema>;

export async function registerPushDevice(
  provider: NotificationProvider = nativeNotificationProvider,
  options: Readonly<{ force?: boolean; nativeToken?: Notifications.DevicePushToken }> = {},
): Promise<boolean> {
  const session = useSessionStore.getState().session;
  if (!session) return false;
  const authentication = captureAuthenticationSnapshot();
  const scope = `${principalAccountNamespace(session.principal)}.${session.sessionId}`;
  const update = (status: PushRegistrationStatus) => {
    const current = useSessionStore.getState().session;
    if (isAuthenticationSnapshotCurrent(authentication)
      && current?.sessionId === session.sessionId
      && principalAccountNamespace(current.principal) === principalAccountNamespace(session.principal)) {
      usePushRegistrationState.getState().update(scope, status);
    }
  };
  if (!session.accessToken || session.networkMode !== 'online') {
    update('offline');
    return false;
  }
  update('registering');
  try {
    const registered = await performPushRegistration(provider, options);
    update(registered ? 'registered' : Device.isDevice ? 'permission_denied' : 'unsupported_device');
    return registered;
  } catch (error) {
    update(error instanceof NotificationRegistrationError
      ? error.code === 'PUSH_PLATFORM_UNSUPPORTED' ? 'unsupported_platform'
        : error.code === 'PUSH_ENVIRONMENT_UNAVAILABLE' ? 'build_unconfigured' : 'token_unavailable'
      : 'registration_failed');
    throw error;
  }
}

async function performPushRegistration(
  provider: NotificationProvider,
  options: Readonly<{ force?: boolean; nativeToken?: Notifications.DevicePushToken }>,
): Promise<boolean> {
  const requestSession = useSessionStore.getState().session;
  if (!requestSession?.accessToken || requestSession.networkMode !== 'online') return false;
  const authentication = captureAuthenticationSnapshot();
  const namespace = principalAccountNamespace(requestSession.principal);
  const registration = await provider.register(options.nativeToken);
  if (!registration) return false;
  const installationId = await getInstallationId();
  const tokenDigest = await Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    registration.token,
  );
  if (!isAuthenticationSnapshotCurrent(authentication)) {
    throw new Error('The active account changed during push registration.');
  }
  const marker = await getPushRegistrationMarker(namespace);
  if (!isAuthenticationSnapshotCurrent(authentication)) {
    throw new Error('The active account changed during push registration.');
  }
  if (useSessionStore.getState().session?.sessionId !== requestSession.sessionId) {
    throw new Error('The active device session changed during push registration.');
  }
  const now = Date.now();
  if (
    !options.force
    && marker?.sessionId === requestSession.sessionId
    && marker.provider === registration.provider
    && marker.apnsEnvironment === registration.apnsEnvironment
    && marker.tokenDigest === tokenDigest
    && marker.installationId === installationId
    && now - marker.registeredAtMs >= 0
    && now - marker.registeredAtMs < PUSH_REGISTRATION_REFRESH_MS
  ) {
    return true;
  }
  const result = await apiRequest('/mobile/push/register', {
    method: 'POST',
    schema: z.object({ registration_id: z.string().uuid(), registered: z.boolean() }).strict(),
    body: {
      provider: registration.provider,
      push_token: registration.token,
      installation_id: installationId,
      ...(registration.provider === 'apns' ? { apns_environment: registration.apnsEnvironment } : {}),
    },
  });
  if (!result.registered) throw new Error('The server did not accept notification registration.');
  if (!isAuthenticationSnapshotCurrent(authentication)) {
    throw new Error('The active account changed during push registration.');
  }
  const current = useSessionStore.getState().session;
  if (current?.sessionId !== requestSession.sessionId) {
    throw new Error('The active device session changed during push registration.');
  }
  await setPushRegistrationMarker(namespace, {
    formatVersion: 1,
    sessionId: requestSession.sessionId,
    provider: registration.provider,
    ...(registration.provider === 'apns' ? { apnsEnvironment: registration.apnsEnvironment } : {}),
    tokenDigest,
    installationId,
    registeredAtMs: now,
  });
  return true;
}

export async function invalidateCurrentPushRegistration(): Promise<void> {
  const session = useSessionStore.getState().session;
  if (!session) return;
  await clearPushRegistrationMarker(principalAccountNamespace(session.principal));
}

export function notificationData(response: Notifications.NotificationResponse): NotificationData | null {
  return notificationContentData(response.notification);
}

export function notificationContentData(notification: Notifications.Notification): NotificationData | null {
  let data = notification.request.content.data;
  // Android's cold-start FCM response includes transport extras alongside the
  // custom data. Strip only those keys; unknown application fields still fail.
  const trigger = notification.request.trigger;
  if (Platform.OS === 'android' && trigger && 'type' in trigger && trigger.type === 'push'
    && data && typeof data === 'object' && !Array.isArray(data)) {
    data = Object.fromEntries(Object.entries(data).filter(([key]) =>
      !key.startsWith('google.') && !key.startsWith('gcm.')
      && !['from', 'collapse_key', 'message_type'].includes(key)));
  }
  const parsed = NotificationDataSchema.safeParse(data);
  return parsed.success ? parsed.data : null;
}

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

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

const PUSH_REGISTRATION_REFRESH_MS = 24 * 60 * 60_000;

export const NotificationDataSchema = z.object({
  route: z.enum(['trip', 'documents', 'qr', 'updates', 'readiness', 'attendance', 'passengers']),
  trip_id: z.string().uuid(),
  event_id: z.string().uuid().optional(),
}).strict();

export type NotificationData = z.infer<typeof NotificationDataSchema>;

export interface NotificationProvider {
  register(): Promise<{ provider: 'expo' | 'fcm' | 'apns'; token: string } | null>;
}

export class NotificationRegistrationError extends Error {
  constructor(readonly code: 'PUSH_PLATFORM_UNSUPPORTED' | 'PUSH_TOKEN_UNAVAILABLE') {
    super(code === 'PUSH_PLATFORM_UNSUPPORTED'
      ? 'Phone alerts are not supported on this platform. Read trip updates in the app.'
      : 'The device push token is temporarily unavailable.');
    this.name = 'NotificationRegistrationError';
  }
}

export async function configureTripUpdateChannel(): Promise<void> {
  if (Platform.OS !== 'android') return;
  await Notifications.setNotificationChannelAsync('trip-updates', {
    name: 'Trip updates',
    importance: Notifications.AndroidImportance.HIGH,
    lockscreenVisibility: Notifications.AndroidNotificationVisibility.PRIVATE,
    vibrationPattern: [0, 180, 90, 240],
    sound: 'default',
  });
}

export async function requestNotificationPermission(): Promise<boolean> {
  if (!Device.isDevice) return false;
  // Android requires the channel before the runtime permission prompt so the
  // operating system can present the final notification behavior accurately.
  await configureTripUpdateChannel();

  const current = await Notifications.getPermissionsAsync();
  const permission = current.granted
    ? current
    : current.canAskAgain
      ? await Notifications.requestPermissionsAsync()
      : current;
  const iosStatus = permission.ios?.status;
  return permission.granted
    || iosStatus === Notifications.IosAuthorizationStatus.PROVISIONAL
    || iosStatus === Notifications.IosAuthorizationStatus.EPHEMERAL;
}

export const fcmNotificationProvider: NotificationProvider = {
  async register() {
    // Retire the installed Expo relay's persisted auto-registration preference.
    // The Metro adapter also prevents its import-time token upload/listener.
    if (Platform.OS !== 'android') {
      throw new NotificationRegistrationError('PUSH_PLATFORM_UNSUPPORTED');
    }
    await Notifications.setAutoServerRegistrationEnabledAsync(false);
    if (!(await requestNotificationPermission())) return null;
    let nativeToken: Notifications.DevicePushToken;
    try {
      nativeToken = await Notifications.getDevicePushTokenAsync();
    } catch {
      throw new NotificationRegistrationError('PUSH_TOKEN_UNAVAILABLE');
    }
    if (nativeToken.type !== 'android' || typeof nativeToken.data !== 'string'
      || nativeToken.data.length < 16 || nativeToken.data.length > 512
      || /[^\x21-\x7e]/.test(nativeToken.data)
      || /^(Exponent|Expo)PushToken\[/.test(nativeToken.data)) {
      throw new NotificationRegistrationError('PUSH_TOKEN_UNAVAILABLE');
    }
    return { provider: 'fcm', token: nativeToken.data };
  },
};

export async function registerPushDevice(
  provider: NotificationProvider = fcmNotificationProvider,
  options: Readonly<{ force?: boolean }> = {},
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
      ? error.code === 'PUSH_PLATFORM_UNSUPPORTED' ? 'unsupported_platform' : 'token_unavailable'
      : 'registration_failed');
    throw error;
  }
}

async function performPushRegistration(
  provider: NotificationProvider,
  options: Readonly<{ force?: boolean }>,
): Promise<boolean> {
  const requestSession = useSessionStore.getState().session;
  if (!requestSession?.accessToken || requestSession.networkMode !== 'online') return false;
  const authentication = captureAuthenticationSnapshot();
  const namespace = principalAccountNamespace(requestSession.principal);
  const registration = await provider.register();
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

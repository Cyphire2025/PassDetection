import * as Application from 'expo-application';
import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import { hasNotificationPermission } from './notification-permission';

export type ApnsEnvironment = 'development' | 'production';
export type NativePushRegistration =
  | { provider: 'fcm'; token: string; apnsEnvironment?: never }
  | { provider: 'apns'; token: string; apnsEnvironment: ApnsEnvironment };

export interface NotificationProvider {
  register(nativeToken?: Notifications.DevicePushToken): Promise<NativePushRegistration | null>;
}

export class NotificationRegistrationError extends Error {
  constructor(readonly code: 'PUSH_PLATFORM_UNSUPPORTED' | 'PUSH_TOKEN_UNAVAILABLE' | 'PUSH_ENVIRONMENT_UNAVAILABLE') {
    super(code === 'PUSH_PLATFORM_UNSUPPORTED'
      ? 'Phone alerts are not supported on this platform. Read updates in the app.'
      : code === 'PUSH_ENVIRONMENT_UNAVAILABLE'
        ? 'This app build is missing its Apple push notification configuration.'
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
  // Create Android's channel before the runtime permission prompt.
  await configureTripUpdateChannel();
  const current = await Notifications.getPermissionsAsync();
  const permission = hasNotificationPermission(current) || !current.canAskAgain
    ? current : await Notifications.requestPermissionsAsync();
  return hasNotificationPermission(permission);
}

async function apnsEnvironment(): Promise<ApnsEnvironment> {
  try {
    // Expo reads aps-environment from the signed provisioning profile. APP_ENV
    // describes our API deployment and cannot determine Apple's token endpoint.
    const environment = await Application.getIosPushNotificationServiceEnvironmentAsync();
    if (environment === 'development' || environment === 'production') return environment;
    // App Store distributions omit embedded.mobileprovision. A native APNs
    // token must already have been obtained before this distribution fallback.
    if (environment === null
      && await Application.getIosApplicationReleaseTypeAsync() === Application.ApplicationReleaseType.APP_STORE) {
      return 'production';
    }
  } catch {
    // Never expose provisioning or native diagnostics to the UI or telemetry.
  }
  throw new NotificationRegistrationError('PUSH_ENVIRONMENT_UNAVAILABLE');
}

export const nativeNotificationProvider: NotificationProvider = {
  async register(receivedToken?: Notifications.DevicePushToken) {
    if (Platform.OS !== 'android' && Platform.OS !== 'ios') {
      throw new NotificationRegistrationError('PUSH_PLATFORM_UNSUPPORTED');
    }
    if (Platform.OS === 'ios' && Constants.expoConfig?.extra?.iosPushNotificationsEnabled === false) {
      throw new NotificationRegistrationError('PUSH_ENVIRONMENT_UNAVAILABLE');
    }
    // Retire the old Expo relay preference; the Metro adapter also suppresses
    // its import-time token upload. Native delivery goes only to our API.
    await Notifications.setAutoServerRegistrationEnabledAsync(false);
    if (!(await requestNotificationPermission())) return null;
    let nativeToken: Notifications.DevicePushToken;
    try {
      nativeToken = receivedToken ?? await Notifications.getDevicePushTokenAsync();
    } catch {
      throw new NotificationRegistrationError('PUSH_TOKEN_UNAVAILABLE');
    }
    if (nativeToken.type !== Platform.OS || typeof nativeToken.data !== 'string'
      || nativeToken.data.length < 16 || nativeToken.data.length > 512) {
      throw new NotificationRegistrationError('PUSH_TOKEN_UNAVAILABLE');
    }
    if (Platform.OS === 'ios') {
      // APNs tokens are hexadecimal, but Apple does not promise a fixed length.
      if (!/^[0-9a-f]+$/i.test(nativeToken.data) || nativeToken.data.length % 2 !== 0) {
        throw new NotificationRegistrationError('PUSH_TOKEN_UNAVAILABLE');
      }
      return { provider: 'apns', token: nativeToken.data.toLowerCase(), apnsEnvironment: await apnsEnvironment() };
    }
    if (/[^\x21-\x7e]/.test(nativeToken.data) || /^(Exponent|Expo)PushToken\[/.test(nativeToken.data)) {
      throw new NotificationRegistrationError('PUSH_TOKEN_UNAVAILABLE');
    }
    return { provider: 'fcm', token: nativeToken.data };
  },
};

/** Android-specific adapter retained for callers that explicitly request FCM. */
export const fcmNotificationProvider: NotificationProvider = {
  async register(receivedToken?: Notifications.DevicePushToken) {
    if (Platform.OS !== 'android') throw new NotificationRegistrationError('PUSH_PLATFORM_UNSUPPORTED');
    return nativeNotificationProvider.register(receivedToken);
  },
};

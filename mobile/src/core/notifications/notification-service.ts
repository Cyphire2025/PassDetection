import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';
import { z } from 'zod';

import { apiRequest } from '@/core/api/client';
import { env } from '@/core/config/env';
import { getInstallationId } from '@/core/storage/secure-store';

export const NotificationDataSchema = z.object({
  route: z.enum(['trip', 'documents', 'qr', 'updates', 'readiness', 'attendance', 'passengers']),
  trip_id: z.string().uuid(),
  event_id: z.string().uuid().optional(),
}).strict();

export type NotificationData = z.infer<typeof NotificationDataSchema>;

export interface NotificationProvider {
  register(): Promise<{ provider: 'expo' | 'fcm' | 'apns'; token: string } | null>;
}

export async function requestNotificationPermission(): Promise<boolean> {
  if (!Device.isDevice) return false;
  if (Platform.OS === 'android') {
    // Android requires the channel before the runtime permission prompt so the
    // operating system can present the final notification behavior accurately.
    await Notifications.setNotificationChannelAsync('trip-updates', {
      name: 'Trip updates',
      importance: Notifications.AndroidImportance.HIGH,
      lockscreenVisibility: Notifications.AndroidNotificationVisibility.PRIVATE,
      vibrationPattern: [0, 180],
    });
  }

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

export const expoNotificationProvider: NotificationProvider = {
  async register() {
    if (!(await requestNotificationPermission()) || !env.easProjectId) return null;
    const token = await Notifications.getExpoPushTokenAsync({ projectId: env.easProjectId });
    return { provider: 'expo', token: token.data };
  },
};

export async function registerPushDevice(provider: NotificationProvider = expoNotificationProvider): Promise<boolean> {
  const registration = await provider.register();
  if (!registration) return false;
  await apiRequest('/mobile/push/register', {
    method: 'POST',
    schema: z.object({ registration_id: z.string().uuid(), registered: z.boolean() }).strict(),
    body: {
      provider: registration.provider,
      push_token: registration.token,
      installation_id: await getInstallationId(),
    },
  });
  return true;
}

export function notificationData(response: Notifications.NotificationResponse): NotificationData | null {
  return notificationContentData(response.notification);
}

export function notificationContentData(notification: Notifications.Notification): NotificationData | null {
  const parsed = NotificationDataSchema.safeParse(notification.request.content.data);
  return parsed.success ? parsed.data : null;
}

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: false,
    shouldSetBadge: false,
  }),
});

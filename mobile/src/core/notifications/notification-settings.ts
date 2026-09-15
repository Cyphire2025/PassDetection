import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

export type NotificationSettings = {
  physicalDevice: boolean;
  permissionGranted: boolean;
  channelBlocked: boolean;
};

/** Inspect OS state without prompting or sending a notification. */
export async function readNotificationSettings(): Promise<NotificationSettings> {
  if (!Device.isDevice) {
    return { physicalDevice: false, permissionGranted: false, channelBlocked: false };
  }
  const permission = await Notifications.getPermissionsAsync();
  const channel = Platform.OS === 'android'
    ? await Notifications.getNotificationChannelAsync('trip-updates')
    : null;
  return {
    physicalDevice: true,
    permissionGranted: permission.granted
      || permission.ios?.status === Notifications.IosAuthorizationStatus.PROVISIONAL
      || permission.ios?.status === Notifications.IosAuthorizationStatus.EPHEMERAL,
    channelBlocked: channel?.importance === Notifications.AndroidImportance.NONE,
  };
}

import * as Notifications from 'expo-notifications';

/** iOS has useful authorized states that are not represented by `granted`. */
export function hasNotificationPermission(permission: Notifications.NotificationPermissionsStatus): boolean {
  if (permission.ios) {
    return permission.ios.status === Notifications.IosAuthorizationStatus.AUTHORIZED
      || permission.ios.status === Notifications.IosAuthorizationStatus.PROVISIONAL
      || permission.ios.status === Notifications.IosAuthorizationStatus.EPHEMERAL;
  }
  return permission.granted;
}

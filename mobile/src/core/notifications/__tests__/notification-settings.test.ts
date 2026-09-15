import { Platform } from 'react-native';

import { readNotificationSettings } from '../notification-settings';

const mockPermission = jest.fn();
const mockChannel = jest.fn();
jest.mock('expo-device', () => ({ isDevice: true }));
jest.mock('expo-notifications', () => ({
  getPermissionsAsync: (...args: unknown[]) => mockPermission(...args),
  getNotificationChannelAsync: (...args: unknown[]) => mockChannel(...args),
  AndroidImportance: { NONE: 0 }, IosAuthorizationStatus: { AUTHORIZED: 2, PROVISIONAL: 3, EPHEMERAL: 4 },
}));

test('reads blocked Android channel without requesting permission', async () => {
  const original = Platform.OS;
  Object.defineProperty(Platform, 'OS', { configurable: true, value: 'android' });
  try {
    mockPermission.mockResolvedValue({ granted: true });
    mockChannel.mockResolvedValue({ importance: 0 });
    await expect(readNotificationSettings()).resolves.toEqual({ physicalDevice: true, permissionGranted: true, channelBlocked: true });
    expect(mockChannel).toHaveBeenCalledWith('trip-updates');
  } finally {
    Object.defineProperty(Platform, 'OS', { configurable: true, value: original });
  }
});


test.each([[2, false, true], [3, false, true], [4, false, true], [1, true, false]])(
  'reads iOS status %i with granted=%s as allowed=%s', async (status, granted, allowed) => {
    const original = Platform.OS;
    Object.defineProperty(Platform, 'OS', { configurable: true, value: 'ios' });
    try {
      mockChannel.mockClear();
      mockPermission.mockResolvedValue({ granted, ios: { status } });
      await expect(readNotificationSettings()).resolves.toEqual({ physicalDevice: true, permissionGranted: allowed, channelBlocked: false });
      expect(mockChannel).not.toHaveBeenCalled();
    } finally { Object.defineProperty(Platform, 'OS', { configurable: true, value: original }); }
  },
);

import * as Application from 'expo-application';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import { nativeNotificationProvider } from '../native-push-provider';

jest.mock('expo-application', () => ({
  ApplicationReleaseType: { UNKNOWN: 0, SIMULATOR: 1, ENTERPRISE: 2, DEVELOPMENT: 3, AD_HOC: 4, APP_STORE: 5 },
  getIosPushNotificationServiceEnvironmentAsync: jest.fn(),
  getIosApplicationReleaseTypeAsync: jest.fn(),
}));
const mockBuild = { pushEnabled: true };
jest.mock('expo-constants', () => ({ __esModule: true, default: {
  get expoConfig() { return { extra: { iosPushNotificationsEnabled: mockBuild.pushEnabled } }; },
} }));
const mockDevice = { isDevice: true };
jest.mock('expo-device', () => ({ get isDevice() { return mockDevice.isDevice; } }));
jest.mock('expo-notifications', () => ({
  IosAuthorizationStatus: { NOT_DETERMINED: 0, DENIED: 1, AUTHORIZED: 2, PROVISIONAL: 3, EPHEMERAL: 4 },
  getPermissionsAsync: jest.fn(), requestPermissionsAsync: jest.fn(),
  getDevicePushTokenAsync: jest.fn(), getExpoPushTokenAsync: jest.fn(),
  setAutoServerRegistrationEnabledAsync: jest.fn(), setNotificationChannelAsync: jest.fn(),
}));

const originalPlatform = Platform.OS;
const permission = (status: number, granted = false, canAskAgain = false) => ({
  granted, canAskAgain, ios: { status },
} as Notifications.NotificationPermissionsStatus);

beforeEach(() => {
  jest.resetAllMocks();
  Object.defineProperty(Platform, 'OS', { configurable: true, value: 'ios' });
  mockDevice.isDevice = true;
  mockBuild.pushEnabled = true;
  jest.mocked(Notifications.getPermissionsAsync).mockResolvedValue(permission(2));
  jest.mocked(Notifications.getDevicePushTokenAsync).mockResolvedValue({ type: 'ios', data: 'ab'.repeat(32) });
  jest.mocked(Application.getIosPushNotificationServiceEnvironmentAsync).mockResolvedValue('development');
  jest.mocked(Application.getIosApplicationReleaseTypeAsync).mockResolvedValue(Application.ApplicationReleaseType.UNKNOWN);
});
afterAll(() => { Object.defineProperty(Platform, 'OS', { configurable: true, value: originalPlatform }); });

test.each([2, 3, 4])('accepts native iOS authorization %i without prompting again', async (status) => {
  jest.mocked(Notifications.getPermissionsAsync).mockResolvedValue(permission(status, false, true));
  await expect(nativeNotificationProvider.register()).resolves.toEqual({
    provider: 'apns', token: 'ab'.repeat(32), apnsEnvironment: 'development',
  });
  expect(Notifications.requestPermissionsAsync).not.toHaveBeenCalled();
  expect(Notifications.getExpoPushTokenAsync).not.toHaveBeenCalled();
  expect(Notifications.setAutoServerRegistrationEnabledAsync).toHaveBeenCalledWith(false);
});

test('uses the native iOS denial even if the cross-platform granted flag disagrees', async () => {
  jest.mocked(Notifications.getPermissionsAsync).mockResolvedValue(permission(1, true));
  await expect(nativeNotificationProvider.register()).resolves.toBeNull();
  expect(Notifications.getDevicePushTokenAsync).not.toHaveBeenCalled();
});

test('requests permission once when iOS allows prompting, then respects denial', async () => {
  jest.mocked(Notifications.getPermissionsAsync).mockResolvedValue(permission(0, false, true));
  jest.mocked(Notifications.requestPermissionsAsync).mockResolvedValue(permission(1));
  await expect(nativeNotificationProvider.register()).resolves.toBeNull();
  expect(Notifications.requestPermissionsAsync).toHaveBeenCalledTimes(1);
  expect(Notifications.getDevicePushTokenAsync).not.toHaveBeenCalled();
});

test('uses production only for an App Store distribution with a valid native APNs token and absent profile', async () => {
  jest.mocked(Application.getIosPushNotificationServiceEnvironmentAsync).mockResolvedValue(null);
  jest.mocked(Application.getIosApplicationReleaseTypeAsync).mockResolvedValue(Application.ApplicationReleaseType.APP_STORE);
  await expect(nativeNotificationProvider.register()).resolves.toMatchObject({ apnsEnvironment: 'production' });
  expect(jest.mocked(Notifications.getDevicePushTokenAsync).mock.invocationCallOrder[0]).toBeLessThan(
    jest.mocked(Application.getIosApplicationReleaseTypeAsync).mock.invocationCallOrder[0]!,
  );
});

test.each([0, 1, 2, 3, 4])('does not guess an APNs endpoint for missing-profile distribution %i', async (releaseType) => {
  jest.mocked(Application.getIosPushNotificationServiceEnvironmentAsync).mockResolvedValue(null);
  jest.mocked(Application.getIosApplicationReleaseTypeAsync).mockResolvedValue(releaseType);
  await expect(nativeNotificationProvider.register()).rejects.toMatchObject({ code: 'PUSH_ENVIRONMENT_UNAVAILABLE' });
});

test('does not expose native profile errors or fall back after a failed profile read', async () => {
  jest.mocked(Application.getIosPushNotificationServiceEnvironmentAsync).mockRejectedValue(new Error('private native diagnostic'));
  await expect(nativeNotificationProvider.register()).rejects.toThrow('missing its Apple push notification configuration');
  expect(Application.getIosApplicationReleaseTypeAsync).not.toHaveBeenCalled();
});

test('does not infer production before native APNs registration succeeds', async () => {
  jest.mocked(Notifications.getDevicePushTokenAsync).mockRejectedValue(new Error('missing entitlement'));
  await expect(nativeNotificationProvider.register()).rejects.toMatchObject({ code: 'PUSH_TOKEN_UNAVAILABLE' });
  expect(Application.getIosApplicationReleaseTypeAsync).not.toHaveBeenCalled();
});

test.each([
  { type: 'android', data: 'ab'.repeat(32) }, { type: 'ios', data: { token: 'ab'.repeat(32) } },
  { type: 'ios', data: 'a'.repeat(15) }, { type: 'ios', data: 'a'.repeat(17) }, { type: 'ios', data: 'a'.repeat(513) },
  { type: 'ios', data: 'ExpoPushToken[legacy-token]' }, { type: 'ios', data: 'gh'.repeat(32) },
  { type: 'ios', data: 'ab cd'.repeat(16) },
])('rejects invalid APNs token without reading a signing profile: %j', async (token) => {
  jest.mocked(Notifications.getDevicePushTokenAsync).mockResolvedValue(token as Notifications.DevicePushToken);
  await expect(nativeNotificationProvider.register()).rejects.toMatchObject({ code: 'PUSH_TOKEN_UNAVAILABLE' });
  expect(Application.getIosPushNotificationServiceEnvironmentAsync).not.toHaveBeenCalled();
});

test.each([16, 512])('accepts bounded hexadecimal APNs tokens of length %i', async (length) => {
  jest.mocked(Notifications.getDevicePushTokenAsync).mockResolvedValue({ type: 'ios', data: 'A'.repeat(length) });
  await expect(nativeNotificationProvider.register()).resolves.toMatchObject({ token: 'a'.repeat(length) });
});

test('does not acquire tokens or read provisioning on an iOS simulator', async () => {
  mockDevice.isDevice = false;
  await expect(nativeNotificationProvider.register()).resolves.toBeNull();
  expect(Notifications.getDevicePushTokenAsync).not.toHaveBeenCalled();
  expect(Application.getIosPushNotificationServiceEnvironmentAsync).not.toHaveBeenCalled();
});

test('registers a rotated native token without requesting a new one recursively', async () => {
  await expect(nativeNotificationProvider.register({ type: 'ios', data: 'cd'.repeat(32) }))
    .resolves.toMatchObject({ provider: 'apns', token: 'cd'.repeat(32) });
  expect(Notifications.getDevicePushTokenAsync).not.toHaveBeenCalled();
});


test('an explicit personal-team build explains unavailable push without acquiring or registering tokens', async () => {
  mockBuild.pushEnabled = false;
  await expect(nativeNotificationProvider.register()).rejects.toMatchObject({ code: 'PUSH_ENVIRONMENT_UNAVAILABLE' });
  expect(Notifications.getPermissionsAsync).not.toHaveBeenCalled();
  expect(Notifications.getDevicePushTokenAsync).not.toHaveBeenCalled();
});

import { Platform } from 'react-native';

import {
  expoNotificationProvider,
  registerPushDevice,
} from '../notification-service';

const mockEnv: { easProjectId: string | undefined } = { easProjectId: undefined };
const mockDevice = { isDevice: true };
const mockGetPermissions = jest.fn();
const mockRequestPermissions = jest.fn();
const mockSetChannel = jest.fn();
const mockGetExpoToken = jest.fn();
const mockApiRequest = jest.fn();
const mockGetInstallationId = jest.fn();

jest.mock('expo-device', () => ({
  get isDevice() {
    return mockDevice.isDevice;
  },
}));

jest.mock('expo-notifications', () => ({
  AndroidImportance: { HIGH: 4 },
  AndroidNotificationVisibility: { PRIVATE: 0 },
  IosAuthorizationStatus: { PROVISIONAL: 3, EPHEMERAL: 4 },
  getPermissionsAsync: (...args: unknown[]) => mockGetPermissions(...args),
  requestPermissionsAsync: (...args: unknown[]) => mockRequestPermissions(...args),
  setNotificationChannelAsync: (...args: unknown[]) => mockSetChannel(...args),
  getExpoPushTokenAsync: (...args: unknown[]) => mockGetExpoToken(...args),
  setNotificationHandler: jest.fn(),
}));

jest.mock('@/core/config/env', () => ({
  get env() {
    return mockEnv;
  },
}));
jest.mock('@/core/api/client', () => ({
  apiRequest: (...args: unknown[]) => mockApiRequest(...args),
}));
jest.mock('@/core/storage/secure-store', () => ({
  getInstallationId: (...args: unknown[]) => mockGetInstallationId(...args),
}));

describe('notification registration', () => {
  const originalPlatform = Platform.OS;

  beforeAll(() => {
    Object.defineProperty(Platform, 'OS', { configurable: true, value: 'android' });
  });

  afterAll(() => {
    Object.defineProperty(Platform, 'OS', { configurable: true, value: originalPlatform });
  });

  beforeEach(() => {
    jest.clearAllMocks();
    mockDevice.isDevice = true;
    mockEnv.easProjectId = undefined;
    mockGetPermissions.mockResolvedValue({ granted: false, canAskAgain: true, ios: null });
    mockRequestPermissions.mockResolvedValue({ granted: true, canAskAgain: true, ios: null });
    mockSetChannel.mockResolvedValue(undefined);
    mockGetExpoToken.mockResolvedValue({ data: 'ExponentPushToken[test]' });
    mockApiRequest.mockResolvedValue({ registered: true, registration_id: 'registration-a' });
    mockGetInstallationId.mockResolvedValue('installation-a');
  });

  it('asks a physical-device user for permission even before an EAS project is configured', async () => {
    await expect(expoNotificationProvider.register()).resolves.toBeNull();

    expect(mockSetChannel).toHaveBeenCalledWith('trip-updates', expect.any(Object));
    expect(mockRequestPermissions).toHaveBeenCalledTimes(1);
    expect(mockGetExpoToken).not.toHaveBeenCalled();
    expect(mockSetChannel.mock.invocationCallOrder[0]!).toBeLessThan(
      mockRequestPermissions.mock.invocationCallOrder[0]!,
    );
  });

  it('gets an Expo token and registers it with the authenticated backend', async () => {
    mockEnv.easProjectId = '123e4567-e89b-42d3-a456-426614174000';
    mockGetPermissions.mockResolvedValue({ granted: true, canAskAgain: true, ios: null });

    await expect(registerPushDevice()).resolves.toBe(true);

    expect(mockGetExpoToken).toHaveBeenCalledWith({ projectId: mockEnv.easProjectId });
    expect(mockApiRequest).toHaveBeenCalledWith('/mobile/push/register', expect.objectContaining({
      method: 'POST',
      body: {
        provider: 'expo',
        push_token: 'ExponentPushToken[test]',
        installation_id: 'installation-a',
      },
    }));
  });

  it('does not request again or register when permission was denied permanently', async () => {
    mockEnv.easProjectId = '123e4567-e89b-42d3-a456-426614174000';
    mockGetPermissions.mockResolvedValue({ granted: false, canAskAgain: false, ios: null });

    await expect(registerPushDevice()).resolves.toBe(false);

    expect(mockRequestPermissions).not.toHaveBeenCalled();
    expect(mockGetExpoToken).not.toHaveBeenCalled();
    expect(mockApiRequest).not.toHaveBeenCalled();
  });
});

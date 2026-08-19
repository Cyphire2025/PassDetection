import { Platform } from 'react-native';

import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';

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
const mockGetPushRegistrationMarker = jest.fn();
const mockSetPushRegistrationMarker = jest.fn();
const mockClearPushRegistrationMarker = jest.fn();
const mockDigestString = jest.fn();

const onlineSession: MobileSession = {
  accessToken: 'access-token',
  accessTokenExpiresAt: '2030-01-01T00:00:00.000Z',
  refreshTokenExpiresAt: '2030-02-01T00:00:00.000Z',
  sessionId: '33333333-3333-4333-8333-333333333333',
  networkMode: 'online',
  principal: {
    id: '22222222-2222-4222-8222-222222222222',
    accountId: '22222222-2222-4222-8222-222222222222',
    principalType: 'passenger',
    agencyId: '11111111-1111-4111-8111-111111111111',
    passengerId: '22222222-2222-4222-8222-222222222222',
    displayName: 'Test Passenger',
    email: null,
    phoneNumber: null,
    forcePasswordChange: false,
  },
};

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
jest.mock('expo-crypto', () => ({
  CryptoDigestAlgorithm: { SHA256: 'SHA-256' },
  digestStringAsync: (...args: unknown[]) => mockDigestString(...args),
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
  getPushRegistrationMarker: (...args: unknown[]) => mockGetPushRegistrationMarker(...args),
  setPushRegistrationMarker: (...args: unknown[]) => mockSetPushRegistrationMarker(...args),
  clearPushRegistrationMarker: (...args: unknown[]) => mockClearPushRegistrationMarker(...args),
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
    useSessionStore.getState().setSession(onlineSession);
    mockDevice.isDevice = true;
    mockEnv.easProjectId = undefined;
    mockGetPermissions.mockResolvedValue({ granted: false, canAskAgain: true, ios: null });
    mockRequestPermissions.mockResolvedValue({ granted: true, canAskAgain: true, ios: null });
    mockSetChannel.mockResolvedValue(undefined);
    mockGetExpoToken.mockResolvedValue({ data: 'ExponentPushToken[test]' });
    mockApiRequest.mockResolvedValue({ registered: true, registration_id: 'registration-a' });
    mockGetInstallationId.mockResolvedValue('44444444-4444-4444-8444-444444444444');
    mockGetPushRegistrationMarker.mockResolvedValue(null);
    mockSetPushRegistrationMarker.mockResolvedValue(undefined);
    mockClearPushRegistrationMarker.mockResolvedValue(undefined);
    mockDigestString.mockResolvedValue('a'.repeat(64));
  });

  it('asks a physical-device user for permission even before an EAS project is configured', async () => {
    await expect(expoNotificationProvider.register()).rejects.toMatchObject({
      code: 'PUSH_PROJECT_NOT_CONFIGURED',
    });

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
        installation_id: '44444444-4444-4444-8444-444444444444',
      },
    }));
    expect(mockSetPushRegistrationMarker).toHaveBeenCalledWith(
      '11111111-1111-4111-8111-111111111111.22222222-2222-4222-8222-222222222222',
      expect.objectContaining({
        sessionId: onlineSession.sessionId,
        provider: 'expo',
        tokenDigest: 'a'.repeat(64),
      }),
    );
  });

  it('does not repeat a current registration with the same session and token fingerprint', async () => {
    mockEnv.easProjectId = '123e4567-e89b-42d3-a456-426614174000';
    mockGetPermissions.mockResolvedValue({ granted: true, canAskAgain: true, ios: null });
    mockGetPushRegistrationMarker.mockResolvedValue({
      formatVersion: 1,
      sessionId: onlineSession.sessionId,
      provider: 'expo',
      tokenDigest: 'a'.repeat(64),
      installationId: '44444444-4444-4444-8444-444444444444',
      registeredAtMs: Date.now(),
    });

    await expect(registerPushDevice()).resolves.toBe(true);

    expect(mockApiRequest).not.toHaveBeenCalled();
    expect(mockSetPushRegistrationMarker).not.toHaveBeenCalled();
  });

  it('does not prompt or bind a token until the cached session is validated online', async () => {
    useSessionStore.getState().setSession({
      ...onlineSession,
      accessToken: null,
      networkMode: 'offline',
    });

    await expect(registerPushDevice()).resolves.toBe(false);

    expect(mockGetPermissions).not.toHaveBeenCalled();
    expect(mockGetExpoToken).not.toHaveBeenCalled();
    expect(mockApiRequest).not.toHaveBeenCalled();
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

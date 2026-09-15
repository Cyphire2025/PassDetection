import { Platform } from 'react-native';

import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';

import {
  fcmNotificationProvider,
  notificationContentData,
  registerPushDevice,
} from '../notification-service';
import { usePushRegistrationState } from '../notification-registration-state';

const mockApnsEnvironment = jest.fn();
const mockReleaseType = jest.fn();
const mockDevice = { isDevice: true };
const mockGetPermissions = jest.fn();
const mockRequestPermissions = jest.fn();
const mockSetChannel = jest.fn();
const mockGetExpoToken = jest.fn();
const mockGetDeviceToken = jest.fn();
const mockSetAutoRegistration = jest.fn();
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

jest.mock('expo-application', () => ({
  getIosPushNotificationServiceEnvironmentAsync: () => mockApnsEnvironment(),
  getIosApplicationReleaseTypeAsync: () => mockReleaseType(),
  ApplicationReleaseType: { APP_STORE: 4 },
}));

jest.mock('expo-device', () => ({
  get isDevice() {
    return mockDevice.isDevice;
  },
}));

jest.mock('expo-notifications', () => ({
  AndroidImportance: { HIGH: 4 },
  AndroidNotificationVisibility: { PRIVATE: 0 },
  IosAuthorizationStatus: { AUTHORIZED: 2, PROVISIONAL: 3, EPHEMERAL: 4 },
  getPermissionsAsync: (...args: unknown[]) => mockGetPermissions(...args),
  requestPermissionsAsync: (...args: unknown[]) => mockRequestPermissions(...args),
  setNotificationChannelAsync: (...args: unknown[]) => mockSetChannel(...args),
  getExpoPushTokenAsync: (...args: unknown[]) => mockGetExpoToken(...args),
  getDevicePushTokenAsync: (...args: unknown[]) => mockGetDeviceToken(...args),
  setAutoServerRegistrationEnabledAsync: (...args: unknown[]) => mockSetAutoRegistration(...args),
  setNotificationHandler: jest.fn(),
}));
jest.mock('expo-crypto', () => ({
  CryptoDigestAlgorithm: { SHA256: 'SHA-256' },
  digestStringAsync: (...args: unknown[]) => mockDigestString(...args),
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

  afterAll(() => {
    Object.defineProperty(Platform, 'OS', { configurable: true, value: originalPlatform });
  });

  beforeEach(() => {
    jest.clearAllMocks();
    Object.defineProperty(Platform, 'OS', { configurable: true, value: 'android' });
    usePushRegistrationState.setState({ scope: null, status: null });
    useSessionStore.getState().setSession(onlineSession);
    mockDevice.isDevice = true;
    mockApnsEnvironment.mockResolvedValue('development');
    mockReleaseType.mockResolvedValue(0);
    mockGetPermissions.mockResolvedValue({ granted: false, canAskAgain: true, ios: null });
    mockRequestPermissions.mockResolvedValue({ granted: true, canAskAgain: true, ios: null });
    mockSetChannel.mockResolvedValue(undefined);
    mockGetExpoToken.mockResolvedValue({ data: 'ExponentPushToken[test]' });
    mockGetDeviceToken.mockResolvedValue({ type: 'android', data: 'native-fcm-token-for-unit-test' });
    mockSetAutoRegistration.mockResolvedValue(undefined);
    mockApiRequest.mockResolvedValue({ registered: true, registration_id: 'registration-a' });
    mockGetInstallationId.mockResolvedValue('44444444-4444-4444-8444-444444444444');
    mockGetPushRegistrationMarker.mockResolvedValue(null);
    mockSetPushRegistrationMarker.mockResolvedValue(undefined);
    mockClearPushRegistrationMarker.mockResolvedValue(undefined);
    mockDigestString.mockResolvedValue('a'.repeat(64));
  });

  it('uses native FCM without an Expo project and creates the channel before prompting', async () => {
    await expect(fcmNotificationProvider.register()).resolves.toEqual({
      provider: 'fcm', token: 'native-fcm-token-for-unit-test',
    });

    expect(mockSetChannel).toHaveBeenCalledWith('trip-updates', expect.any(Object));
    expect(mockRequestPermissions).toHaveBeenCalledTimes(1);
    expect(mockGetExpoToken).not.toHaveBeenCalled();
    expect(mockSetAutoRegistration).toHaveBeenCalledWith(false);
    expect(mockSetChannel.mock.invocationCallOrder[0]!).toBeLessThan(
      mockRequestPermissions.mock.invocationCallOrder[0]!,
    );
  });

  it('gets a native FCM token and registers it with the authenticated backend', async () => {
    mockGetPermissions.mockResolvedValue({ granted: true, canAskAgain: true, ios: null });

    await expect(registerPushDevice()).resolves.toBe(true);

    expect(mockGetDeviceToken).toHaveBeenCalledWith();
    expect(mockGetExpoToken).not.toHaveBeenCalled();
    expect(mockApiRequest).toHaveBeenCalledWith('/mobile/push/register', expect.objectContaining({
      method: 'POST',
      body: {
        provider: 'fcm',
        push_token: 'native-fcm-token-for-unit-test',
        installation_id: '44444444-4444-4444-8444-444444444444',
      },
    }));
    expect(mockSetPushRegistrationMarker).toHaveBeenCalledWith(
      '11111111-1111-4111-8111-111111111111.22222222-2222-4222-8222-222222222222',
      expect.objectContaining({
        sessionId: onlineSession.sessionId,
        provider: 'fcm',
        tokenDigest: 'a'.repeat(64),
      }),
    );
  });

  it('does not repeat a current registration with the same session and token fingerprint', async () => {
    mockGetPermissions.mockResolvedValue({ granted: true, canAskAgain: true, ios: null });
    mockGetPushRegistrationMarker.mockResolvedValue({
      formatVersion: 1,
      sessionId: onlineSession.sessionId,
      provider: 'fcm',
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
    expect(mockGetDeviceToken).not.toHaveBeenCalled();
    expect(mockGetExpoToken).not.toHaveBeenCalled();
    expect(mockApiRequest).not.toHaveBeenCalled();
  });

  it('does not request again or register when permission was denied permanently', async () => {
    mockGetPermissions.mockResolvedValue({ granted: false, canAskAgain: false, ios: null });

    await expect(registerPushDevice()).resolves.toBe(false);

    expect(mockRequestPermissions).not.toHaveBeenCalled();
    expect(mockGetDeviceToken).not.toHaveBeenCalled();
    expect(mockGetExpoToken).not.toHaveBeenCalled();
    expect(mockApiRequest).not.toHaveBeenCalled();
    expect(usePushRegistrationState.getState().status).toBe('permission_denied');
  });

  it('reports a safe error and does not mark an explicitly rejected registration as registered', async () => {
    mockApiRequest.mockResolvedValue({ registered: false, registration_id: 'registration-a' });
    await expect(registerPushDevice()).rejects.toThrow();
    expect(usePushRegistrationState.getState().status).toBe('registration_failed');
    expect(mockSetPushRegistrationMarker).not.toHaveBeenCalled();
  });

  it('force retry re-registers a current marker and exposes a confirmed result', async () => {
    mockGetPushRegistrationMarker.mockResolvedValue({ sessionId: onlineSession.sessionId,
      provider: 'fcm', tokenDigest: 'a'.repeat(64), installationId: '44444444-4444-4444-8444-444444444444',
      registeredAtMs: Date.now(), formatVersion: 1 });
    await expect(registerPushDevice(undefined, { force: true })).resolves.toBe(true);
    expect(mockApiRequest).toHaveBeenCalledTimes(1);
    expect(usePushRegistrationState.getState().status).toBe('registered');
  });

  it('does not publish a late registration result into a different account session', async () => {
    mockApiRequest.mockImplementation(async () => {
      useSessionStore.getState().setSession({ ...onlineSession, sessionId: 'different-session' });
      return { registered: true, registration_id: 'registration-a' };
    });
    await expect(registerPushDevice()).rejects.toThrow('active device session changed');
    expect(usePushRegistrationState.getState().status).toBe('registering');
    expect(usePushRegistrationState.getState().scope).toContain(onlineSession.sessionId);
    expect(mockSetPushRegistrationMarker).not.toHaveBeenCalled();
  });

  it('replaces a legacy Expo marker on the same installation without resetting the login', async () => {
    mockGetPushRegistrationMarker.mockResolvedValue({ sessionId: onlineSession.sessionId,
      provider: 'expo', tokenDigest: 'a'.repeat(64), installationId: '44444444-4444-4444-8444-444444444444',
      registeredAtMs: Date.now(), formatVersion: 1 });
    await expect(registerPushDevice()).resolves.toBe(true);
    expect(mockApiRequest).toHaveBeenCalledTimes(1);
    expect(mockSetPushRegistrationMarker).toHaveBeenCalledWith(expect.any(String),
      expect.objectContaining({ provider: 'fcm', sessionId: onlineSession.sessionId }));
    expect(useSessionStore.getState().session).toEqual(onlineSession);
  });

  it('refreshes registration when the native token rotates', async () => {
    mockGetPushRegistrationMarker.mockResolvedValue({ sessionId: onlineSession.sessionId,
      provider: 'fcm', tokenDigest: 'b'.repeat(64), installationId: '44444444-4444-4444-8444-444444444444',
      registeredAtMs: Date.now(), formatVersion: 1 });
    await expect(registerPushDevice()).resolves.toBe(true);
    expect(mockApiRequest).toHaveBeenCalledTimes(1);
  });

  it('reports an unsupported platform without registering a native token', async () => {
    Object.defineProperty(Platform, 'OS', { configurable: true, value: 'web' });
    await expect(registerPushDevice()).rejects.toMatchObject({ code: 'PUSH_PLATFORM_UNSUPPORTED' });
    expect(usePushRegistrationState.getState().status).toBe('unsupported_platform');
    expect(mockGetPermissions).not.toHaveBeenCalled();
    expect(mockGetDeviceToken).not.toHaveBeenCalled();
    expect(mockGetExpoToken).not.toHaveBeenCalled();
    expect(mockApiRequest).not.toHaveBeenCalled();
  });

  it.each(['development', 'production'])('registers APNs with its signed %s environment', async (environment) => {
    Object.defineProperty(Platform, 'OS', { configurable: true, value: 'ios' });
    mockApnsEnvironment.mockResolvedValue(environment);
    mockGetDeviceToken.mockResolvedValue({ type: 'ios', data: 'AB'.repeat(32) });
    await expect(registerPushDevice()).resolves.toBe(true);
    expect(mockApiRequest).toHaveBeenCalledWith('/mobile/push/register', expect.objectContaining({
      body: { provider: 'apns', push_token: 'ab'.repeat(32), apns_environment: environment,
        installation_id: '44444444-4444-4444-8444-444444444444' },
    }));
    expect(mockSetPushRegistrationMarker).toHaveBeenCalledWith(expect.any(String),
      expect.objectContaining({ provider: 'apns', apnsEnvironment: environment }));
    expect(mockSetChannel).not.toHaveBeenCalled();
    expect(mockGetExpoToken).not.toHaveBeenCalled();
  });

  it.each([undefined, 'development', 'production'])('refreshes legacy/changed APNs environment %s correctly', async (savedEnvironment) => {
    Object.defineProperty(Platform, 'OS', { configurable: true, value: 'ios' });
    mockApnsEnvironment.mockResolvedValue('production');
    mockGetDeviceToken.mockResolvedValue({ type: 'ios', data: 'ab'.repeat(32) });
    mockGetPushRegistrationMarker.mockResolvedValue({ sessionId: onlineSession.sessionId,
      provider: 'apns', apnsEnvironment: savedEnvironment, tokenDigest: 'a'.repeat(64),
      installationId: '44444444-4444-4444-8444-444444444444', registeredAtMs: Date.now(), formatVersion: 1 });
    await expect(registerPushDevice()).resolves.toBe(true);
    expect(mockApiRequest).toHaveBeenCalledTimes(savedEnvironment === 'production' ? 0 : 1);
  });

  it('shows missing signed Apple configuration as a build issue without registering', async () => {
    Object.defineProperty(Platform, 'OS', { configurable: true, value: 'ios' });
    mockGetDeviceToken.mockResolvedValue({ type: 'ios', data: 'ab'.repeat(32) });
    mockApnsEnvironment.mockResolvedValue(null);
    await expect(registerPushDevice()).rejects.toMatchObject({ code: 'PUSH_ENVIRONMENT_UNAVAILABLE' });
    expect(usePushRegistrationState.getState().status).toBe('build_unconfigured');
    expect(mockApiRequest).not.toHaveBeenCalled();
  });

  it('does not register a simulator or claim phone alerts are ready', async () => {
    mockDevice.isDevice = false;
    await expect(registerPushDevice()).resolves.toBe(false);
    expect(usePushRegistrationState.getState().status).toBe('unsupported_device');
    expect(mockGetDeviceToken).not.toHaveBeenCalled();
    expect(mockApiRequest).not.toHaveBeenCalled();
  });

  it.each([
    { type: 'ios', data: 'native-fcm-token-for-unit-test' },
    { type: 'android', data: { token: 'not-a-token-string' } },
    { type: 'android', data: 'short' },
    { type: 'android', data: 'x'.repeat(513) },
    { type: 'android', data: 'native token with spaces' },
    { type: 'android', data: 'ExpoPushToken[legacy]' },
    { type: 'android', data: 'ExponentPushToken[legacy]' },
  ])('rejects an invalid native token without sending it to the API: %j', async (token) => {
    mockGetDeviceToken.mockResolvedValue(token);
    await expect(registerPushDevice()).rejects.toMatchObject({ code: 'PUSH_TOKEN_UNAVAILABLE' });
    expect(usePushRegistrationState.getState().status).toBe('token_unavailable');
    expect(mockApiRequest).not.toHaveBeenCalled();
  });

  it('hides native credential errors behind a safe retryable token status', async () => {
    mockGetDeviceToken.mockRejectedValue(new Error('private native diagnostic'));
    await expect(registerPushDevice()).rejects.toThrow('The device push token is temporarily unavailable.');
    expect(usePushRegistrationState.getState().status).toBe('token_unavailable');
    expect(mockApiRequest).not.toHaveBeenCalled();
  });

  it('does not bind a token after the account changes during native registration', async () => {
    mockGetDeviceToken.mockImplementation(async () => {
      useSessionStore.getState().clear();
      return { type: 'android', data: 'native-fcm-token-for-unit-test' };
    });
    await expect(registerPushDevice()).rejects.toThrow('active account changed');
    expect(mockApiRequest).not.toHaveBeenCalled();
    expect(mockSetPushRegistrationMarker).not.toHaveBeenCalled();
  });

  it('does not send the registration into a replacement session while reading its marker', async () => {
    mockGetPushRegistrationMarker.mockImplementation(async () => {
      useSessionStore.getState().setSession({ ...onlineSession, sessionId: 'replacement-session' });
      return null;
    });
    await expect(registerPushDevice()).rejects.toThrow('active device session changed');
    expect(mockApiRequest).not.toHaveBeenCalled();
    expect(mockSetPushRegistrationMarker).not.toHaveBeenCalled();
  });

  it.each([16, 512])('accepts native tokens at the API length boundary %i', async (length) => {
    mockGetDeviceToken.mockResolvedValue({ type: 'android', data: 'x'.repeat(length) });
    await expect(registerPushDevice()).resolves.toBe(true);
    expect(mockApiRequest).toHaveBeenCalledWith('/mobile/push/register', expect.objectContaining({
      body: expect.objectContaining({ provider: 'fcm', push_token: 'x'.repeat(length) }),
    }));
  });
});

describe('direct FCM notification routing payloads', () => {
  const originalPlatform = Platform.OS;
  const route = { route: 'updates', trip_id: '11111111-1111-4111-8111-111111111111',
    event_id: '22222222-2222-4222-8222-222222222222' };
  const notification = (data: Record<string, unknown>, type = 'push') => ({
    request: { content: { data }, trigger: { type } },
  } as Parameters<typeof notificationContentData>[0]);
  beforeEach(() => { Object.defineProperty(Platform, 'OS', { configurable: true, value: 'android' }); });
  afterAll(() => { Object.defineProperty(Platform, 'OS', { configurable: true, value: originalPlatform }); });

  it('accepts the native serializer’s flat foreground FCM map', () => {
    expect(notificationContentData(notification(route))).toEqual(route);
  });
  it('accepts the cold-start extras map while ignoring only Google transport metadata', () => {
    expect(notificationContentData(notification({ ...route, 'google.message_id': 'message-1',
      'google.sent_time': 1, 'google.ttl': 3600, 'gcm.n.e': '1', from: 'test-sender',
      collapse_key: 'test-package' }))).toEqual(route);
  });
  it('still rejects unknown application fields and unsafe destinations', () => {
    expect(notificationContentData(notification({ ...route, url: 'https://example.test' }))).toBeNull();
    expect(notificationContentData(notification({ ...route, route: '/admin' }))).toBeNull();
    expect(notificationContentData(notification({ ...route, trip_id: 'untrusted' }))).toBeNull();
    expect(notificationContentData(notification({ body: JSON.stringify(route) }))).toBeNull();
  });
  it('does not broaden local or iOS notification payloads for Android extras', () => {
    expect(notificationContentData(notification({ ...route, from: 'test' }, 'date'))).toBeNull();
    Object.defineProperty(Platform, 'OS', { configurable: true, value: 'ios' });
    expect(notificationContentData(notification({ ...route, from: 'test' }))).toBeNull();
  });
});


describe('standalone phone-alert payloads', () => {
  const event = '22222222-2222-4222-8222-222222222222';
  const notification = (data: Record<string, unknown>) => ({
    request: { content: { data }, trigger: { type: 'push' } },
  } as Parameters<typeof notificationContentData>[0]);
  it('accepts an identified Updates alert without an announcement or trip', () => {
    expect(notificationContentData(notification({ route: 'updates', event_id: event })))
      .toEqual({ route: 'updates', event_id: event });
  });
  it.each([{ route: 'updates' }, { route: 'attendance', event_id: event },
    { route: 'updates', event_id: 'invalid' }, { route: 'updates', event_id: event, url: '/admin' }])
  ('rejects an unsafe or ambiguous standalone payload %j', (data) => {
    expect(notificationContentData(notification(data))).toBeNull();
  });
  it('accepts the iOS native serializer result from the APNs custom body object', () => {
    const apnsPayload = { aps: { alert: { title: 'Travel message', body: 'Open the app' } },
      body: { route: 'updates', event_id: event } };
    expect(notificationContentData(notification(apnsPayload.body))).toEqual(apnsPayload.body);
    expect(notificationContentData(notification(apnsPayload))).toBeNull();
  });
});

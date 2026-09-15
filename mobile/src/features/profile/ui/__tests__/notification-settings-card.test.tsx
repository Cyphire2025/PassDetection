import { fireEvent, render, waitFor } from '@testing-library/react-native';
import { Linking, Platform } from 'react-native';

import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';
import { usePushRegistrationState } from '@/core/notifications/notification-registration-state';
import { registerPushDevice } from '@/core/notifications/notification-service';
import { readNotificationSettings } from '@/core/notifications/notification-settings';

import { NotificationSettingsCard } from '../notification-settings-card';

jest.mock('@/core/demo/demo-mode', () => ({ isDemoMode: () => false }));
jest.mock('@/core/notifications/notification-service', () => ({ registerPushDevice: jest.fn() }));
jest.mock('@/core/notifications/notification-settings', () => ({ readNotificationSettings: jest.fn() }));

const account: MobileSession = {
  accessToken: 'token', accessTokenExpiresAt: '2030-01-01T00:00:00Z', refreshTokenExpiresAt: '2030-02-01T00:00:00Z',
  sessionId: 'session-a', networkMode: 'online',
  principal: { id: 'passenger-a', accountId: 'account-a', agencyId: 'agency-a',
    principalType: 'passenger', displayName: 'Passenger', email: null, phoneNumber: null,
    forcePasswordChange: false },
};

const originalPlatform = Platform.OS;
afterAll(() => { Object.defineProperty(Platform, 'OS', { configurable: true, value: originalPlatform }); });
beforeEach(() => {
  jest.clearAllMocks();
  Object.defineProperty(Platform, 'OS', { configurable: true, value: 'android' });
  useSessionStore.getState().setSession(account);
  usePushRegistrationState.setState({ scope: null, status: null });
  jest.mocked(readNotificationSettings).mockResolvedValue({ physicalDevice: true, permissionGranted: true, channelBlocked: false });
  jest.mocked(registerPushDevice).mockResolvedValue(true);
});

afterEach(() => { useSessionStore.getState().clear(); jest.restoreAllMocks(); });

test('permission denial is actionable and opens this app’s phone settings', async () => {
  jest.mocked(readNotificationSettings).mockResolvedValue({ physicalDevice: true, permissionGranted: false, channelBlocked: false });
  const openSettings = jest.spyOn(Linking, 'openSettings').mockResolvedValue();
  const screen = await render(<NotificationSettingsCard />);
  await waitFor(() => expect(screen.getByText(/Phone notifications are not allowed/)).toBeTruthy());
  await fireEvent.press(screen.getByText('Open phone notification settings'));
  expect(openSettings).toHaveBeenCalledTimes(1);
});

test('retry forces registration without sending a test notification', async () => {
  const screen = await render(<NotificationSettingsCard />);
  await fireEvent.press(screen.getByText('Retry notification registration'));
  await waitFor(() => expect(registerPushDevice).toHaveBeenCalledWith(undefined, { force: true }));
});

test('a blocked Android channel is shown even after a successful registration', async () => {
  usePushRegistrationState.getState().update('agency-a.account-a.session-a', 'registered');
  jest.mocked(readNotificationSettings).mockResolvedValue({ physicalDevice: true, permissionGranted: true, channelBlocked: true });
  const screen = await render(<NotificationSettingsCard />);
  await waitFor(() => expect(screen.getByText(/Trip updates are blocked/)).toBeTruthy());
});

test('does not show another session’s successful registration', async () => {
  usePushRegistrationState.getState().update('agency-a.account-a.session-old', 'registered');
  const screen = await render(<NotificationSettingsCard />);
  await waitFor(() => expect(screen.getByText(/has not been confirmed in this session/)).toBeTruthy());
  expect(screen.queryByText(/This device is registered/)).toBeNull();
});

test('iOS offers in-app updates and cannot claim Android delivery is ready', async () => {
  Object.defineProperty(Platform, 'OS', { configurable: true, value: 'ios' });
  usePushRegistrationState.getState().update('agency-a.account-a.session-a', 'registered');
  const screen = await render(<NotificationSettingsCard />);
  await waitFor(() => expect(screen.getByText(/Phone alerts are available on Android only/)).toBeTruthy());
  expect(screen.getByText(/Read Updates in the app/)).toBeTruthy();
  expect(screen.queryByText(/This device is registered/)).toBeNull();
  await fireEvent.press(screen.getByText('Retry notification registration'));
  expect(registerPushDevice).not.toHaveBeenCalled();
});

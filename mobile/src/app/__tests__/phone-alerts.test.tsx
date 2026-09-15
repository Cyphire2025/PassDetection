import { fireEvent, render } from '@testing-library/react-native';
import type { PropsWithChildren } from 'react';

import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';
import { usePhoneAlerts } from '@/features/notifications/hooks/use-phone-alerts';

import PhoneAlertsScreen from '../phone-alerts';

const mockMarkRead = jest.fn();
const mockBack = jest.fn();
const mockReplace = jest.fn();
jest.mock('expo-router', () => {
  const { Text } = jest.requireActual<typeof import('react-native')>('react-native');
  return {
  Redirect: ({ href }: { href: string }) => <Text>{`redirect:${href}`}</Text>,
  useRouter: () => ({ back: mockBack, replace: mockReplace, canGoBack: () => false }),
}; });
jest.mock('@/features/notifications/hooks/use-phone-alerts', () => ({ usePhoneAlerts: jest.fn() }));
jest.mock('@/design/components/content-state', () => {
  const { Text } = jest.requireActual<typeof import('react-native')>('react-native');
  return { ContentLoading: ({ label }: { label: string }) => <Text>{label}</Text>,
    ContentEmpty: ({ title }: { title: string }) => <Text>{title}</Text>,
    ContentError: ({ message }: { message: string }) => <Text>{message}</Text> };
});
jest.mock('@/design/components/loading-screen', () => ({ LoadingScreen: () => null }));
jest.mock('@/design/components/screen', () => {
  const { View } = jest.requireActual<typeof import('react-native')>('react-native');
  return { Screen: ({ children }: PropsWithChildren) => <View>{children}</View> };
});
jest.mock('@/design/components/page-header', () => {
  const { Text } = jest.requireActual<typeof import('react-native')>('react-native');
  return { PageHeader: ({ title }: { title: string }) => <Text>{title}</Text> };
});

const session: MobileSession = {
  accessToken: 'test-token', accessTokenExpiresAt: '2030-01-01T00:00:00Z',
  refreshTokenExpiresAt: '2030-02-01T00:00:00Z', sessionId: 'session-a', networkMode: 'online',
  principal: { id: 'user-a', accountId: 'account-a', agencyId: 'agency-a', principalType: 'passenger',
    displayName: 'Test', email: null, phoneNumber: null, forcePasswordChange: false },
};
const item = { id: '11111111-1111-4111-8111-111111111111', title: 'Meeting time changed',
  body: 'Please meet at the hotel desk at 8 AM.', priority: 'emergency' as const, read_at: null,
  trip_id: null, notification_type: 'gc_alert', category: 'gc_alert', payload: {},
  deep_link_path: '/phone-alerts', available_at: '2026-09-15T00:00:00Z', expires_at: null };
function setInbox(overrides: Record<string, unknown> = {}) {
  jest.mocked(usePhoneAlerts).mockReturnValue({ items: [item], online: true,
    isPending: false, isError: false, isRefetching: false, hasNextPage: false,
    markingRead: false, readFailed: false, markRead: mockMarkRead, ...overrides,
  } as unknown as ReturnType<typeof usePhoneAlerts>);
}
beforeEach(() => { jest.clearAllMocks(); useSessionStore.getState().setSession(session); setInbox(); });
afterEach(() => useSessionStore.getState().clear());

test('requires authentication before mounting the inbox query', async () => {
  useSessionStore.getState().clear();
  const screen = await render(<PhoneAlertsScreen />);
  expect(screen.getByText('redirect:/(auth)/welcome')).toBeTruthy();
  expect(usePhoneAlerts).not.toHaveBeenCalled();
});

test('renders authored title/body/priority and marks the own recipient row as read', async () => {
  const screen = await render(<PhoneAlertsScreen />);
  expect(screen.getByText(item.title)).toBeTruthy();
  expect(screen.getByText(item.body)).toBeTruthy();
  expect(screen.getByText('emergency')).toBeTruthy();
  await fireEvent.press(screen.getByLabelText(`Unread phone alert: ${item.title}`));
  expect(mockMarkRead).toHaveBeenCalledWith(item.id);
});

test('an offline cached list explains refresh limits and does not submit read actions', async () => {
  setInbox({ online: false });
  const screen = await render(<PhoneAlertsScreen />);
  expect(screen.getByText('Connect to refresh phone alerts')).toBeTruthy();
  await fireEvent.press(screen.getByLabelText(`Unread phone alert: ${item.title}`));
  expect(mockMarkRead).not.toHaveBeenCalled();
});

test('a cold-start inbox can return safely to the role home without a back history', async () => {
  const screen = await render(<PhoneAlertsScreen />);
  await fireEvent.press(screen.getByText('Back'));
  expect(mockReplace).toHaveBeenCalledWith('/');
  expect(mockBack).not.toHaveBeenCalled();
});

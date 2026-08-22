import { act, render } from '@testing-library/react-native';
import type { PropsWithChildren, ReactNode } from 'react';

import { useSessionStore } from '@/core/auth/session-store';

import { RootNavigation } from '../_layout';

type StackComponent = ((props: PropsWithChildren) => ReactNode) & {
  Protected: (props: PropsWithChildren<{ guard: boolean }>) => ReactNode;
  Screen: (props: { name: string }) => ReactNode;
};

jest.mock('expo-router', () => {
  const React = jest.requireActual<typeof import('react')>('react');
  const ReactNative = jest.requireActual<typeof import('react-native')>('react-native');
  const Stack = (({ children }: PropsWithChildren) => children) as StackComponent;
  Stack.Protected = function MockProtected({
    children,
    guard,
  }: PropsWithChildren<{ guard: boolean }>) {
    return guard ? children : null;
  };
  Stack.Screen = function MockScreen({ name }: { name: string }) {
    return React.createElement(ReactNative.View, { testID: `root-screen:${name}` });
  };
  return { Stack };
});

jest.mock('expo-splash-screen', () => ({
  preventAutoHideAsync: jest.fn(async () => undefined),
}));

jest.mock('@/core/observability/mobile-observability', () => ({
  initializeMobileObservability: jest.fn(),
}));

jest.mock('@/core/errors/application-error-boundary', () => ({
  ApplicationErrorBoundary: ({ children }: PropsWithChildren) => children,
}));

jest.mock('@/design/accessibility/use-reduced-motion', () => ({
  navigationAnimation: () => 'none',
  useReducedMotion: () => true,
}));

jest.mock('@/providers/app-providers', () => ({
  AppProviders: ({ children }: PropsWithChildren) => {
    const React = jest.requireActual<typeof import('react')>('react');
    const ReactNative = jest.requireActual<typeof import('react-native')>('react-native');
    return React.createElement(ReactNative.View, null, children);
  },
}));

const passengerSession = {
  accessToken: 'a'.repeat(48),
  accessTokenExpiresAt: '2026-08-03T12:00:00.000Z',
  refreshTokenExpiresAt: '2026-09-03T12:00:00.000Z',
  sessionId: '33333333-3333-4333-8333-333333333333',
  networkMode: 'online' as const,
  principal: {
    id: '22222222-2222-4222-8222-222222222222',
    accountId: '22222222-2222-4222-8222-222222222222',
    principalType: 'passenger' as const,
    agencyId: '11111111-1111-4111-8111-111111111111',
    displayName: 'Passenger',
    email: null,
    phoneNumber: '+919876543210',
    forcePasswordChange: false,
  },
};

afterEach(() => useSessionStore.getState().clear());

test('removes every authenticated route from navigation history when sign-out clears the session', async () => {
  useSessionStore.getState().setSession(passengerSession);
  const screen = await render(<RootNavigation />);

  expect(screen.getByTestId('root-screen:(passenger)')).toBeTruthy();
  expect(screen.getByTestId('root-screen:document/[id]')).toBeTruthy();
  expect(screen.queryByTestId('root-screen:(manager)')).toBeNull();
  expect(screen.queryByTestId('root-screen:(coordinator)')).toBeNull();

  await act(async () => {
    useSessionStore.getState().clear();
  });

  expect(screen.queryByTestId('root-screen:(passenger)')).toBeNull();
  expect(screen.queryByTestId('root-screen:document/[id]')).toBeNull();
  expect(screen.queryByTestId('root-screen:(manager)')).toBeNull();
  expect(screen.queryByTestId('root-screen:(coordinator)')).toBeNull();
  expect(screen.getByTestId('root-screen:index')).toBeTruthy();
  expect(screen.getByTestId('root-screen:(auth)')).toBeTruthy();
});

/* eslint-disable @typescript-eslint/no-require-imports -- Jest factories load mocked host components after hoisting. */
import { act, render } from '@testing-library/react-native';

import type { MobileSession } from '@/core/auth/types';

import RequiredPreparationScreen from '../prepare';

const mockReplace = jest.fn();
const mockPreload = jest.fn();

const SESSION: MobileSession = {
  accessToken: 'access-token',
  accessTokenExpiresAt: '2026-08-04T00:00:00.000Z',
  refreshTokenExpiresAt: '2026-09-04T00:00:00.000Z',
  sessionId: '33333333-3333-4333-8333-333333333333',
  networkMode: 'online',
  principal: {
    id: '22222222-2222-4222-8222-222222222222',
    accountId: '22222222-2222-4222-8222-222222222222',
    principalType: 'passenger',
    agencyId: '11111111-1111-4111-8111-111111111111',
    displayName: 'Passenger One',
    email: null,
    phoneNumber: '+919876543210',
    forcePasswordChange: false,
  },
};

let mockSession: MobileSession | null = SESSION;

jest.mock('expo-router', () => {
  const React = require('react') as typeof import('react');
  const { Text } = require('react-native') as typeof import('react-native');
  return {
    Redirect: ({ href }: { href: string }) => React.createElement(Text, null, href),
    router: { replace: (...args: unknown[]) => mockReplace(...args) },
  };
});
jest.mock('@/core/auth/session-store', () => ({
  useSessionStore: (selector: (state: { session: MobileSession | null }) => unknown) => (
    selector({ session: mockSession })
  ),
}));
jest.mock('@/core/sync/required-preload', () => ({
  preloadAuthenticatedWorkspace: (...args: unknown[]) => mockPreload(...args),
}));
jest.mock('@/design/components/required-download-screen', () => {
  const React = require('react') as typeof import('react');
  const { Text, View } = require('react-native') as typeof import('react-native');
  return {
    RequiredDownloadScreen: ({ message, error, errorSecondaryAction }: {
      message: string;
      error?: string | null;
      errorSecondaryAction?: React.ReactNode;
    }) => (
      React.createElement(
        View,
        null,
        React.createElement(Text, null, error ?? message),
        errorSecondaryAction,
      )
    ),
  };
});
jest.mock('@/features/profile/ui/safe-sign-out-button', () => {
  const React = require('react') as typeof import('react');
  const { Text } = require('react-native') as typeof import('react-native');
  return {
    SafeSignOutButton: ({ label }: { label: string }) => React.createElement(Text, null, label),
  };
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  jest.clearAllMocks();
  mockSession = SESSION;
});

it('navigates immediately when required preparation succeeds', async () => {
  const preparation = deferred<{ destination: '/(passenger)/(tabs)/trip' }>();
  mockPreload.mockReturnValue(preparation.promise);
  await render(<RequiredPreparationScreen />);

  await act(async () => {
    preparation.resolve({ destination: '/(passenger)/(tabs)/trip' });
    await preparation.promise;
  });

  expect(mockReplace).toHaveBeenCalledWith('/(passenger)/(tabs)/trip');
});

it('ignores completion from a stale account preparation run', async () => {
  const first = deferred<{ destination: '/(passenger)/(tabs)/trip' }>();
  const second = deferred<{ destination: '/(passenger)/select-trip' }>();
  mockPreload.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  const screen = await render(<RequiredPreparationScreen />);

  mockSession = { ...SESSION, sessionId: '44444444-4444-4444-8444-444444444444' };
  await screen.rerender(<RequiredPreparationScreen />);

  await act(async () => {
    first.resolve({ destination: '/(passenger)/(tabs)/trip' });
    await first.promise;
  });
  expect(mockReplace).not.toHaveBeenCalled();

  await act(async () => {
    second.resolve({ destination: '/(passenger)/select-trip' });
    await second.promise;
  });
  expect(mockReplace).toHaveBeenCalledTimes(1);
  expect(mockReplace).toHaveBeenCalledWith('/(passenger)/select-trip');
});

it('renders stable user-safe copy instead of native database diagnostics', async () => {
  const preparation = deferred<never>();
  mockPreload.mockReturnValue(preparation.promise);
  const screen = await render(<RequiredPreparationScreen />);

  await act(async () => {
    preparation.reject(new Error(
      'Call to function NativeDatabase.execAsync has been rejected: cannot rollback - no transaction is active',
    ));
    await preparation.promise.catch(() => undefined);
  });

  expect(screen.getByText('Required offline data could not be prepared. Try again.')).toBeTruthy();
  expect(screen.getByText('Sign out and return to login')).toBeTruthy();
  expect(screen.queryByText(/NativeDatabase|rollback|transaction/i)).toBeNull();
});

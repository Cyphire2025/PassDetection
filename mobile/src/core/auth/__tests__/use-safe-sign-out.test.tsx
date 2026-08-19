import { act, renderHook } from '@testing-library/react-native';

import { logoutSession, purgeLocalSession } from '../session-service';
import { useSessionStore } from '../session-store';
import { useSafeSignOut } from '../use-safe-sign-out';

jest.mock('../session-service', () => ({
  logoutSession: jest.fn(),
  purgeLocalSession: jest.fn(),
}));

const mockedLogout = jest.mocked(logoutSession);
const mockedPurge = jest.mocked(purgeLocalSession);
const mockCancelDepartureReminders = jest.fn(async () => undefined);
const namespace = '11111111-1111-4111-8111-111111111111.22222222-2222-4222-8222-222222222222';

jest.mock('@/core/notifications/departure-reminders', () => ({
  cancelDepartureReminders: () => mockCancelDepartureReminders(),
}));

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

beforeEach(() => {
  mockedLogout.mockReset();
  mockedPurge.mockReset();
  mockCancelDepartureReminders.mockClear();
  mockedPurge.mockResolvedValue(undefined);
  useSessionStore.getState().setSession({
    accessToken: 'a'.repeat(48),
    accessTokenExpiresAt: '2026-08-03T12:00:00.000Z',
    refreshTokenExpiresAt: '2026-09-03T12:00:00.000Z',
    sessionId: '33333333-3333-4333-8333-333333333333',
    networkMode: 'online',
    principal: {
      id: '22222222-2222-4222-8222-222222222222',
      accountId: '22222222-2222-4222-8222-222222222222',
      principalType: 'passenger',
      agencyId: '11111111-1111-4111-8111-111111111111',
      displayName: 'Passenger',
      email: null,
      phoneNumber: '+919876543210',
      forcePasswordChange: false,
    },
  });
});

test('a rejected logout is handled and exposes a non-sensitive cleanup retry', async () => {
  mockedLogout.mockRejectedValueOnce(new Error('/private/device/path failed'));
  const { result } = await renderHook(() => useSafeSignOut());

  let request!: Promise<void>;
  await act(async () => {
    request = result.current.signOut();
    await request;
  });
  await expect(request).resolves.toBeUndefined();

  expect(result.current.isSigningOut).toBe(false);
  expect(result.current.errorMessage).toBe(
    'Signed out locally, but secure data cleanup is incomplete. Try again or contact support.',
  );
  expect(result.current.errorMessage).not.toContain('/private/device/path');

  await act(async () => {
    await result.current.retryCleanup();
  });
  expect(mockedPurge).toHaveBeenCalledWith(namespace);
  expect(result.current.errorMessage).toBeNull();
});

test('duplicate sign-out taps share one request and invoke logout once', async () => {
  const pending = deferred<void>();
  const logoutStarted = deferred<void>();
  mockedLogout.mockImplementationOnce(() => {
    logoutStarted.resolve();
    return pending.promise;
  });
  const { result } = await renderHook(() => useSafeSignOut());

  let first!: Promise<void>;
  let second!: Promise<void>;
  await act(async () => {
    first = result.current.signOut();
    second = result.current.signOut();
    await logoutStarted.promise;
  });

  expect(second).toBe(first);
  expect(mockedLogout).toHaveBeenCalledTimes(1);
  expect(mockCancelDepartureReminders).not.toHaveBeenCalled();
  expect(result.current.isSigningOut).toBe(true);

  await act(async () => {
    pending.resolve();
    await first;
  });
  expect(mockCancelDepartureReminders).toHaveBeenCalledTimes(1);
  expect(result.current.isSigningOut).toBe(false);
});

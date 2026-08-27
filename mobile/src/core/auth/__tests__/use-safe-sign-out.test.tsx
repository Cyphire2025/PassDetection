import { act, renderHook } from '@testing-library/react-native';

import { UnsynchronizedActionsError } from '@/core/storage/pending-action-safety';

import { lockLocalSession, logoutSession } from '../session-service';
import { useSessionStore } from '../session-store';
import { useSafeSignOut } from '../use-safe-sign-out';

jest.mock('../session-service', () => ({
  lockLocalSession: jest.fn(),
  logoutSession: jest.fn(),
}));

const mockedLogout = jest.mocked(logoutSession);
const mockedLock = jest.mocked(lockLocalSession);
const mockRequestSync = jest.fn(async (..._args: unknown[]) => ({
  results: [],
  failures: [],
  requestedTripCount: 0,
  tripsChanged: false,
  removedTripIds: [],
}));
const mockCancelDepartureReminders = jest.fn(async () => undefined);
jest.mock('@/core/notifications/departure-reminders', () => ({
  cancelDepartureReminders: () => mockCancelDepartureReminders(),
}));

jest.mock('@/core/sync/sync-trigger', () => ({
  requestSync: (...args: unknown[]) => mockRequestSync(...args),
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
  mockedLock.mockReset();
  mockRequestSync.mockClear();
  mockCancelDepartureReminders.mockClear();
  mockedLock.mockResolvedValue(undefined);
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
    'Sign-out could not finish securely locking local data. Try again or contact support.',
  );
  expect(result.current.errorMessage).not.toContain('/private/device/path');

  await act(async () => {
    await result.current.retryCleanup();
  });
  expect(mockedLogout).toHaveBeenCalledTimes(2);
  expect(mockedLock).not.toHaveBeenCalled();
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

test('blocks ordinary sign-out, then synchronizes and retries without discarding the queue', async () => {
  const summary = {
    pending: 4,
    sending: 1,
    retryable: 2,
    unresolvedReview: 0,
    unsynchronized: 7,
    unsynchronizedAttendanceScans: 6,
    unsynchronizedDiscardAudits: 0,
    unsynchronizedOtherActions: 1,
  } as const;
  mockedLogout
    .mockRejectedValueOnce(new UnsynchronizedActionsError(summary))
    .mockResolvedValueOnce(undefined);
  const { result } = await renderHook(() => useSafeSignOut());

  await act(async () => {
    await result.current.signOut();
  });
  expect(result.current.blockedActions).toEqual(summary);
  expect(result.current.errorMessage).toBe(
    '6 scans have not reached the server, with 1 other unsynchronized change.',
  );
  expect(mockCancelDepartureReminders).not.toHaveBeenCalled();

  await act(async () => {
    await result.current.synchronizeAndSignOut();
  });
  expect(mockRequestSync).toHaveBeenCalledWith({ scope: 'full', reason: 'sign-out-guard' });
  expect(mockedLogout).toHaveBeenNthCalledWith(2, {});
  expect(mockedLogout).not.toHaveBeenCalledWith({ discardUnsynchronizedActions: true });
  expect(mockCancelDepartureReminders).toHaveBeenCalledTimes(1);
});

test('uses the destructive logout option only after the caller explicitly selects discard', async () => {
  mockedLogout.mockResolvedValue(undefined);
  const { result } = await renderHook(() => useSafeSignOut());

  await act(async () => {
    await result.current.discardAndSignOut();
  });

  expect(mockedLogout).toHaveBeenCalledWith({ discardUnsynchronizedActions: true });
});

import * as BackgroundTask from 'expo-background-task';
import * as TaskManager from 'expo-task-manager';

import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';

import { BACKGROUND_SYNC_TASK, runBackgroundSyncTask } from '../background-sync';
import { requestSync } from '../sync-trigger';

const mockBootstrapSession = jest.fn(async (_options?: unknown) => undefined);
const mockRetryPendingTripPurges = jest.fn(async () => undefined);
const mockPurgeExpiredTripCaches = jest.fn(async () => [] as string[]);

jest.mock('expo-background-task', () => ({
  BackgroundTaskResult: { Success: 1, Failed: 2 },
  addExpirationListener: jest.fn(() => ({ remove: jest.fn() })),
  registerTaskAsync: jest.fn(async () => undefined),
  unregisterTaskAsync: jest.fn(async () => undefined),
}));

jest.mock('expo-task-manager', () => ({
  isTaskDefined: jest.fn(() => false),
  defineTask: jest.fn(),
  isAvailableAsync: jest.fn(async () => true),
  isTaskRegisteredAsync: jest.fn(async () => false),
}));

jest.mock('@/core/auth/session-service', () => ({
  bootstrapSession: (options?: unknown) => mockBootstrapSession(options),
}));

jest.mock('../access-cache', () => ({
  retryPendingTripPurges: () => mockRetryPendingTripPurges(),
  purgeExpiredTripCaches: () => mockPurgeExpiredTripCaches(),
}));

jest.mock('../sync-trigger', () => ({
  requestSync: jest.fn(),
}));

const mockedRequestSync = jest.mocked(requestSync);

const session: MobileSession = {
  accessToken: 'access-token',
  accessTokenExpiresAt: '2030-01-01T01:00:00.000Z',
  refreshTokenExpiresAt: '2030-02-01T00:00:00.000Z',
  sessionId: 'session-passenger',
  networkMode: 'online',
  principal: {
    id: 'principal-a',
    accountId: 'account-a',
    principalType: 'passenger',
    agencyId: 'agency-a',
    displayName: 'Passenger',
    email: null,
    phoneNumber: null,
    forcePasswordChange: false,
  },
};

function registeredTask(): () => Promise<number> {
  const registration = jest.mocked(TaskManager.defineTask).mock.calls.find(
    ([taskName]) => taskName === BACKGROUND_SYNC_TASK,
  );
  if (!registration) throw new Error('Background task was not registered.');
  return registration[1] as unknown as () => Promise<number>;
}

beforeEach(() => {
  mockedRequestSync.mockReset();
  mockBootstrapSession.mockClear();
  mockRetryPendingTripPurges.mockClear();
  mockPurgeExpiredTripCaches.mockClear();
  jest.mocked(BackgroundTask.addExpirationListener).mockClear();
  jest.mocked(BackgroundTask.addExpirationListener).mockImplementation(
    () => ({ remove: jest.fn() }),
  );
  useSessionStore.getState().setSession(session);
});

test('the OS task reports failure when every assigned trip fails', async () => {
  mockedRequestSync.mockResolvedValue({
    results: [],
    failures: [
      { tripId: 'trip-a', category: 'network', retryable: true, code: 'SYNC_NETWORK' },
      { tripId: 'trip-b', category: 'server', retryable: true, code: 'SYNC_SERVER' },
    ],
    requestedTripCount: 2,
    tripsChanged: false,
    removedTripIds: [],
  });

  await expect(registeredTask()()).resolves.toBe(BackgroundTask.BackgroundTaskResult.Failed);
  expect(mockBootstrapSession).toHaveBeenCalledWith({ execution: 'native-background' });
});

test('the OS task reports failure for an observable partial sync', async () => {
  mockedRequestSync.mockResolvedValue({
    results: [{
      tripId: 'trip-a',
      cursor: 2,
      changes: 1,
      changed: true,
      syncedAt: '2030-01-01T00:00:00.000Z',
      documentPrefetch: null,
    }],
    failures: [
      { tripId: 'trip-b', category: 'network', retryable: true, code: 'SYNC_NETWORK' },
    ],
    requestedTripCount: 2,
    tripsChanged: false,
    removedTripIds: [],
  });

  await expect(registeredTask()()).resolves.toBe(BackgroundTask.BackgroundTaskResult.Failed);
});

test('an empty assignment is a successful background no-op', async () => {
  mockedRequestSync.mockResolvedValue({
    results: [],
    failures: [],
    requestedTripCount: 0,
    tripsChanged: false,
    removedTripIds: [],
  });

  await expect(registeredTask()()).resolves.toBe(BackgroundTask.BackgroundTaskResult.Success);
});

test('the operating-system expiration callback cooperatively aborts active sync work', async () => {
  let receivedSignal: AbortSignal | null = null;
  mockedRequestSync.mockImplementation((_trigger, { signal } = {}) => {
    receivedSignal = signal ?? null;
    return new Promise((_resolve, reject) => {
      signal?.addEventListener('abort', () => reject(signal.reason), { once: true });
    });
  });

  const task = registeredTask()();
  for (let attempt = 0; attempt < 10 && mockedRequestSync.mock.calls.length === 0; attempt += 1) {
    await Promise.resolve();
  }
  expect(mockedRequestSync).toHaveBeenCalledWith(
    { scope: 'full', reason: 'native-background' },
    { signal: expect.any(AbortSignal) },
  );
  const expirationListener = jest.mocked(BackgroundTask.addExpirationListener).mock.calls[0]?.[0];
  expect(expirationListener).toBeDefined();
  expirationListener?.();

  await expect(task).resolves.toBe(BackgroundTask.BackgroundTaskResult.Failed);
  expect(receivedSignal).not.toBeNull();
  expect((receivedSignal as unknown as AbortSignal).aborted).toBe(true);
  const subscription = jest.mocked(BackgroundTask.addExpirationListener).mock.results[0]?.value;
  expect(subscription?.remove).toHaveBeenCalledTimes(1);
});

test('the internal safety deadline aborts work even when the OS callback is late', async () => {
  jest.useFakeTimers();
  try {
    mockedRequestSync.mockImplementation((_trigger, { signal } = {}) => new Promise((_resolve, reject) => {
      signal?.addEventListener('abort', () => reject(signal.reason), { once: true });
    }));

    const task = runBackgroundSyncTask(1_000);
    for (let attempt = 0; attempt < 10 && mockedRequestSync.mock.calls.length === 0; attempt += 1) {
      await Promise.resolve();
    }
    expect(mockedRequestSync).toHaveBeenCalledWith(
      { scope: 'full', reason: 'native-background' },
      { signal: expect.any(AbortSignal) },
    );
    await jest.advanceTimersByTimeAsync(1_000);

    await expect(task).resolves.toBe(BackgroundTask.BackgroundTaskResult.Failed);
    const signal = mockedRequestSync.mock.calls[0]?.[1]?.signal;
    expect(signal?.aborted).toBe(true);
  } finally {
    jest.useRealTimers();
  }
});

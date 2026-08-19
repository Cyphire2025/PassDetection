import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';

import {
  captureSyncContext,
  SyncContextChangedError,
} from '../sync-context';
import { FULL_TRIP_RECONCILIATION_INTERVAL_MS } from '../sync-runtime-policy';
import {
  SyncCoordinator,
  type SyncCoordinatorDependencies,
} from '../sync-trigger';
import type {
  SyncAllTripsSummary,
  SyncResult,
  SyncTripFailure,
} from '../sync-service';

const tripResult = (tripId: string): SyncResult => ({
  tripId,
  cursor: 1,
  changes: 1,
  changed: true,
  syncedAt: '2026-08-19T00:00:00.000Z',
  documentPrefetch: null,
});

const fullSummary = (tripIds: string[] = []): SyncAllTripsSummary => ({
  results: tripIds.map(tripResult),
  failures: [],
  requestedTripCount: tripIds.length,
  tripsChanged: false,
  removedTripIds: [],
});

function session(accountId: string, sessionId: string): MobileSession {
  return {
    accessToken: `access-${accountId}`,
    accessTokenExpiresAt: '2030-01-01T00:00:00.000Z',
    refreshTokenExpiresAt: '2030-02-01T00:00:00.000Z',
    sessionId,
    networkMode: 'online',
    principal: {
      id: `principal-${accountId}`,
      accountId,
      principalType: 'client_manager',
      agencyId: 'agency-a',
      displayName: 'Manager',
      email: null,
      phoneNumber: null,
      forcePasswordChange: false,
    },
  };
}

function boundaryKey(): string | null {
  const active = useSessionStore.getState().session;
  if (!active) return null;
  return [
    `${active.principal.agencyId}.${active.principal.accountId}`,
    active.sessionId,
    active.principal.id,
    active.principal.principalType,
  ].join(':');
}

function dependencies(
  overrides: Partial<SyncCoordinatorDependencies> = {},
): SyncCoordinatorDependencies {
  return {
    captureLease: (signal) => captureSyncContext(signal),
    currentBoundaryKey: boundaryKey,
    executeFull: jest.fn(async () => fullSummary()),
    executeTrip: jest.fn(async (tripId) => tripResult(tripId)),
    failureForTrip: jest.fn((tripId, error): SyncTripFailure => ({
      tripId,
      category: 'network',
      retryable: true,
      code: error instanceof Error ? error.name : 'UNKNOWN',
    })),
    loadFullWatermark: jest.fn(async () => null),
    storeFullWatermark: jest.fn(async () => undefined),
    publish: jest.fn(async () => undefined),
    afterFull: jest.fn(async () => undefined),
    now: jest.fn(() => 10_000),
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  useSessionStore.getState().setSession(session('account-a', 'session-a'));
});

afterEach(() => useSessionStore.getState().clear());

test('coalesces a synchronous trip trigger storm into one logical synchronization', async () => {
  const deps = dependencies();
  const coordinator = new SyncCoordinator(deps);

  const requests = Array.from({ length: 50 }, (_, index) => coordinator.request({
    scope: 'trip',
    tripId: 'trip-a',
    reason: `storm-${index}`,
  }));

  await expect(Promise.all(requests)).resolves.toHaveLength(50);
  expect(deps.executeTrip).toHaveBeenCalledTimes(1);
  expect(deps.executeFull).not.toHaveBeenCalled();
  expect(deps.publish).toHaveBeenCalledTimes(1);
});

test('a full request wins over concurrent trip requests in the same burst', async () => {
  const executeFull = jest.fn(async () => fullSummary(['trip-a']));
  const deps = dependencies({ executeFull });
  const coordinator = new SyncCoordinator(deps);

  const trip = coordinator.request({ scope: 'trip', tripId: 'trip-a', reason: 'preload' });
  const full = coordinator.request({ scope: 'full', reason: 'foreground' });

  await expect(Promise.all([trip, full])).resolves.toHaveLength(2);
  expect(executeFull).toHaveBeenCalledTimes(1);
  expect(deps.executeTrip).not.toHaveBeenCalled();
});

test('joins matching active work and queues one stronger follow-up request', async () => {
  let releaseTrip!: () => void;
  const tripGate = new Promise<void>((resolve) => { releaseTrip = resolve; });
  const executeTrip = jest.fn(async (tripId: string) => {
    if (tripId === 'trip-a') await tripGate;
    return tripResult(tripId);
  });
  const executeFull = jest.fn(async () => fullSummary(['trip-b']));
  const deps = dependencies({ executeFull, executeTrip });
  const coordinator = new SyncCoordinator(deps);

  const first = coordinator.request({ scope: 'trip', tripId: 'trip-a', reason: 'preload' });
  await Promise.resolve();
  await Promise.resolve();
  expect(executeTrip).toHaveBeenCalledTimes(1);

  const joined = coordinator.request({ scope: 'trip', tripId: 'trip-a', reason: 'manual' });
  const coveredByFull = coordinator.request({ scope: 'trip', tripId: 'trip-b', reason: 'push' });
  const full = coordinator.request({ scope: 'full', reason: 'realtime-overflow' });
  releaseTrip();

  await expect(Promise.all([first, joined, coveredByFull, full])).resolves.toHaveLength(4);
  expect(executeTrip).toHaveBeenCalledTimes(1);
  expect(executeFull).toHaveBeenCalledTimes(1);
});

test('loads the persisted full watermark after restart and scopes it by account', async () => {
  const stored = new Map<string, number>();
  let now = 50_000;
  const makeDependencies = () => dependencies({
    executeFull: jest.fn(async () => fullSummary(['trip-a'])),
    loadFullWatermark: jest.fn(async (context) => stored.get(context.namespace) ?? null),
    storeFullWatermark: jest.fn(async (context, value) => {
      stored.set(context.namespace, value);
    }),
    now: () => now,
  });

  const firstDeps = makeDependencies();
  const firstProcess = new SyncCoordinator(firstDeps);
  await firstProcess.request({ scope: 'auto', tripId: 'trip-a', reason: 'startup' });
  expect(firstDeps.executeFull).toHaveBeenCalledTimes(1);
  expect(stored.get('agency-a.account-a')).toBe(now);

  now += FULL_TRIP_RECONCILIATION_INTERVAL_MS - 1;
  const restartedDeps = makeDependencies();
  const restartedProcess = new SyncCoordinator(restartedDeps);
  await restartedProcess.request({ scope: 'auto', tripId: 'trip-a', reason: 'restart' });
  expect(restartedDeps.executeFull).not.toHaveBeenCalled();
  expect(restartedDeps.executeTrip).toHaveBeenCalledTimes(1);

  useSessionStore.getState().setSession(session('account-b', 'session-b'));
  const accountBDeps = makeDependencies();
  const accountBProcess = new SyncCoordinator(accountBDeps);
  await accountBProcess.request({ scope: 'auto', tripId: 'trip-b', reason: 'account-switch' });
  expect(accountBDeps.executeFull).toHaveBeenCalledTimes(1);
  expect(stored.get('agency-a.account-b')).toBe(now);
});

test('does not poison a failed request and allows the next trigger to retry', async () => {
  const failure = new TypeError('Network request failed');
  const executeTrip = jest.fn()
    .mockRejectedValueOnce(failure)
    .mockResolvedValueOnce(tripResult('trip-a'));
  const deps = dependencies({ executeTrip });
  const coordinator = new SyncCoordinator(deps);

  await expect(coordinator.request({
    scope: 'trip', tripId: 'trip-a', reason: 'first',
  })).rejects.toBe(failure);
  await expect(coordinator.request({
    scope: 'trip', tripId: 'trip-a', reason: 'retry',
  })).resolves.toMatchObject({ failures: [] });
  expect(executeTrip).toHaveBeenCalledTimes(2);
});

test('records a full watermark only after successful projection publication', async () => {
  const publicationFailure = new Error('local projection publication failed');
  const publish = jest.fn()
    .mockRejectedValueOnce(publicationFailure)
    .mockResolvedValueOnce(undefined);
  const storeFullWatermark = jest.fn(async () => undefined);
  const executeFull = jest.fn(async () => fullSummary(['trip-a']));
  const deps = dependencies({ executeFull, publish, storeFullWatermark });
  const coordinator = new SyncCoordinator(deps);

  await expect(coordinator.request({
    scope: 'auto', tripId: 'trip-a', reason: 'first',
  })).rejects.toBe(publicationFailure);
  expect(storeFullWatermark).not.toHaveBeenCalled();

  await expect(coordinator.request({
    scope: 'auto', tripId: 'trip-a', reason: 'retry',
  })).resolves.toMatchObject({ failures: [] });
  expect(executeFull).toHaveBeenCalledTimes(2);
  expect(storeFullWatermark).toHaveBeenCalledTimes(1);
});

test('does not mark a partial full reconciliation as successfully complete', async () => {
  const retryableFailure: SyncTripFailure = {
    tripId: 'trip-b',
    category: 'network',
    retryable: true,
    code: 'SYNC_NETWORK',
  };
  const executeFull = jest.fn()
    .mockResolvedValueOnce({
      ...fullSummary(['trip-a']),
      failures: [retryableFailure],
      requestedTripCount: 2,
    })
    .mockResolvedValueOnce(fullSummary(['trip-a', 'trip-b']));
  const storeFullWatermark = jest.fn(async () => undefined);
  const deps = dependencies({ executeFull, storeFullWatermark });
  const coordinator = new SyncCoordinator(deps);

  await expect(coordinator.request({
    scope: 'auto', tripId: 'trip-a', reason: 'partial',
  })).resolves.toMatchObject({ failures: [retryableFailure] });
  expect(storeFullWatermark).not.toHaveBeenCalled();

  await expect(coordinator.request({
    scope: 'auto', tripId: 'trip-a', reason: 'retry',
  })).resolves.toMatchObject({ failures: [] });
  expect(executeFull).toHaveBeenCalledTimes(2);
  expect(storeFullWatermark).toHaveBeenCalledTimes(1);
});

test('cancels the old account before publishing and allows the new account to proceed', async () => {
  const publishedNamespaces: string[] = [];
  const executeTrip = jest.fn((tripId: string, context: Parameters<SyncCoordinatorDependencies['executeTrip']>[1]) => {
    if (context.namespace === 'agency-a.account-b') return Promise.resolve(tripResult(tripId));
    return new Promise<SyncResult>((_resolve, reject) => {
      const cancelled = () => reject(context.signal.reason);
      context.signal.addEventListener('abort', cancelled, { once: true });
    });
  });
  const deps = dependencies({
    executeTrip,
    publish: jest.fn(async (_summary, context) => {
      publishedNamespaces.push(context.namespace);
    }),
  });
  const coordinator = new SyncCoordinator(deps);

  const oldAccount = coordinator.request({
    scope: 'trip', tripId: 'trip-a', reason: 'account-a',
  });
  await Promise.resolve();
  await Promise.resolve();
  useSessionStore.getState().setSession(session('account-b', 'session-b'));
  const newAccount = coordinator.request({
    scope: 'trip', tripId: 'trip-b', reason: 'account-b',
  });

  await expect(oldAccount).rejects.toBeInstanceOf(SyncContextChangedError);
  await expect(newAccount).resolves.toMatchObject({ failures: [] });
  expect(publishedNamespaces).toEqual(['agency-a.account-b']);
});

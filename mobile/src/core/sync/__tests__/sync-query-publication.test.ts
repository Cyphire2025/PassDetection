import { QueryClient, QueryObserver } from '@tanstack/react-query';

import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';

import { captureSyncContext } from '../sync-context';
import { publishSyncSummary } from '../sync-query-publication';
import type { SyncAllTripsSummary } from '../sync-service';

const session: MobileSession = {
  accessToken: 'access-account-a',
  accessTokenExpiresAt: '2030-01-01T00:00:00.000Z',
  refreshTokenExpiresAt: '2030-02-01T00:00:00.000Z',
  sessionId: 'session-account-a',
  networkMode: 'online',
  principal: {
    id: 'principal-account-a',
    accountId: 'account-a',
    principalType: 'client_manager',
    agencyId: 'agency-a',
    displayName: 'Manager',
    email: null,
    phoneNumber: null,
    forcePasswordChange: false,
  },
};

const changedSummary: SyncAllTripsSummary = {
  results: [{
    tripId: 'trip-a',
    cursor: 2,
    changes: 1,
    changed: true,
    syncedAt: '2026-08-19T00:00:00.000Z',
    documentPrefetch: null,
  }],
  failures: [],
  requestedTripCount: 1,
  tripsChanged: false,
  removedTripIds: [],
};

beforeEach(() => useSessionStore.getState().setSession(session));
afterEach(() => useSessionStore.getState().clear());

test('active publication rereads local projections without refetching unrelated remote queries', async () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  let localProjectionReads = 0;
  let unrelatedRemoteReads = 0;
  let otherAccountReads = 0;
  const projection = new QueryObserver(queryClient, {
    queryKey: ['trip-itinerary', 'trip-a', 'agency-a.account-a'],
    queryFn: async () => ({ revision: ++localProjectionReads }),
  });
  const unrelated = new QueryObserver(queryClient, {
    queryKey: ['mobile-notifications', 'trip-a', 'agency-a.account-a'],
    queryFn: async () => ({ revision: ++unrelatedRemoteReads }),
  });
  const otherAccount = new QueryObserver(queryClient, {
    queryKey: ['trip-itinerary', 'trip-a', 'agency-a.account-b'],
    queryFn: async () => ({ revision: ++otherAccountReads }),
  });
  const unsubscribeProjection = projection.subscribe(() => undefined);
  const unsubscribeUnrelated = unrelated.subscribe(() => undefined);
  const unsubscribeOther = otherAccount.subscribe(() => undefined);
  await Promise.all([
    projection.refetch(),
    unrelated.refetch(),
    otherAccount.refetch(),
  ]);
  expect(localProjectionReads).toBe(1);
  expect(unrelatedRemoteReads).toBe(1);
  expect(otherAccountReads).toBe(1);

  const lease = captureSyncContext();
  try {
    await publishSyncSummary(changedSummary, lease.context, queryClient);
  } finally {
    lease.release();
  }

  expect(localProjectionReads).toBe(2);
  expect(projection.getCurrentResult().data).toEqual({ revision: 2 });
  expect(unrelatedRemoteReads).toBe(1);
  expect(otherAccountReads).toBe(1);

  unsubscribeProjection();
  unsubscribeUnrelated();
  unsubscribeOther();
  queryClient.clear();
});

test('unchanged synchronization does not republish active projections', async () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let reads = 0;
  const observer = new QueryObserver(queryClient, {
    queryKey: ['trip-room', 'trip-a', 'agency-a.account-a'],
    queryFn: async () => ++reads,
  });
  const unsubscribe = observer.subscribe(() => undefined);
  await observer.refetch();
  const lease = captureSyncContext();
  try {
    await publishSyncSummary({
      ...changedSummary,
      results: [{ ...changedSummary.results[0]!, changed: false }],
    }, lease.context, queryClient);
  } finally {
    lease.release();
  }
  expect(reads).toBe(1);
  unsubscribe();
  queryClient.clear();
});

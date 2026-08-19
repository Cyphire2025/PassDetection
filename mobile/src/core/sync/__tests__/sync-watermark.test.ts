import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';
import { captureSyncContext, SyncContextChangedError } from '../sync-context';
import {
  loadLastSuccessfulFullSyncAt,
  storeLastSuccessfulFullSyncAt,
} from '../sync-watermark';

const storedWatermarks = new Map<string, number>();
const mockOpenAccountDatabase = jest.fn(async (namespace: string) => ({
  getFirstAsync: jest.fn(async (_sql: string, accountNamespace: string) => {
    const value = storedWatermarks.get(`${namespace}:${accountNamespace}`);
    return value === undefined
      ? null
      : { last_successful_full_sync_at_epoch_ms: value };
  }),
  runAsync: jest.fn(async (
    _sql: string,
    accountNamespace: string,
    completedAtEpochMs: number,
  ) => {
    storedWatermarks.set(`${namespace}:${accountNamespace}`, completedAtEpochMs);
    return { changes: 1 };
  }),
}));

jest.mock('@/core/storage/database', () => ({
  openAccountDatabase: (namespace: string) => mockOpenAccountDatabase(namespace),
}));

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
      principalType: 'coordinator',
      agencyId: 'agency-a',
      displayName: 'Coordinator',
      email: null,
      phoneNumber: null,
      forcePasswordChange: false,
    },
  };
}

beforeEach(() => {
  storedWatermarks.clear();
  jest.clearAllMocks();
  useSessionStore.getState().setSession(session('account-a', 'session-a-1'));
});

afterEach(() => useSessionStore.getState().clear());

test('persists the last successful full-sync watermark across coordinator restart', async () => {
  const firstLease = captureSyncContext();
  await storeLastSuccessfulFullSyncAt(firstLease.context, 123_456);
  firstLease.release();

  useSessionStore.getState().setSession(session('account-a', 'session-a-2'));
  const restartedLease = captureSyncContext();
  await expect(loadLastSuccessfulFullSyncAt(restartedLease.context)).resolves.toBe(123_456);
  restartedLease.release();
});

test('isolates watermarks by account namespace and rejects a stale account context', async () => {
  const accountALease = captureSyncContext();
  await storeLastSuccessfulFullSyncAt(accountALease.context, 100);

  useSessionStore.getState().setSession(session('account-b', 'session-b'));
  await expect(loadLastSuccessfulFullSyncAt(accountALease.context))
    .rejects.toBeInstanceOf(SyncContextChangedError);
  accountALease.release();

  const accountBLease = captureSyncContext();
  await expect(loadLastSuccessfulFullSyncAt(accountBLease.context)).resolves.toBeNull();
  await storeLastSuccessfulFullSyncAt(accountBLease.context, 200);
  await expect(loadLastSuccessfulFullSyncAt(accountBLease.context)).resolves.toBe(200);
  accountBLease.release();

  expect(storedWatermarks).toEqual(new Map([
    ['agency-a.account-a:agency-a.account-a', 100],
    ['agency-a.account-b:agency-a.account-b', 200],
  ]));
});

test('rejects invalid persisted watermark values before writing', async () => {
  const lease = captureSyncContext();
  await expect(storeLastSuccessfulFullSyncAt(lease.context, Number.NaN))
    .rejects.toThrow('watermark was invalid');
  await expect(storeLastSuccessfulFullSyncAt(lease.context, -1))
    .rejects.toThrow('watermark was invalid');
  lease.release();
  expect(storedWatermarks).toEqual(new Map());
});

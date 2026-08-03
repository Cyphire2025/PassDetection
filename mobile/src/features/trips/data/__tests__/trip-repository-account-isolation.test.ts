import { apiRequest, ApiError } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';
import { captureSyncContext } from '@/core/sync/sync-context';

import { localTrips, refreshTrips, refreshTripsInContext } from '../trip-repository';

jest.mock('@/core/api/client', () => ({
  ...jest.requireActual('@/core/api/client'),
  apiRequest: jest.fn(),
}));
jest.mock('@/core/storage/database', () => ({
  openAccountDatabase: jest.fn(),
  withAccountTransaction: jest.fn(async (database, task) => task(database)),
}));
jest.mock('@/core/sync/access-cache', () => ({
  purgeTripCache: jest.fn(),
  retryPendingTripPurges: jest.fn(async () => ({
    completedTripIds: [],
    pendingTripIds: [],
  })),
  TripVaultPurgePendingError: class TripVaultPurgePendingError extends Error {},
}));

const mockedApiRequest = jest.mocked(apiRequest);
const mockedOpenDatabase = jest.mocked(openAccountDatabase);
const mockedTransaction = jest.mocked(withAccountTransaction);

async function waitForCall(mock: jest.Mock): Promise<void> {
  for (let index = 0; index < 20; index += 1) {
    if (mock.mock.calls.length > 0) return;
    await Promise.resolve();
  }
  throw new Error('The expected asynchronous boundary was not reached.');
}

function session(account: 'a' | 'b'): MobileSession {
  return {
    accessToken: `access-${account}`,
    accessTokenExpiresAt: '2030-01-01T00:00:00.000Z',
    refreshTokenExpiresAt: '2030-02-01T00:00:00.000Z',
    sessionId: `session-${account}`,
    networkMode: 'online',
    principal: {
      id: `principal-${account}`,
      accountId: `principal-${account}`,
      principalType: 'passenger',
      agencyId: `agency-${account}`,
      displayName: `Account ${account}`,
      email: null,
      phoneNumber: null,
      forcePasswordChange: false,
    },
  };
}

const tripPage = {
  items: [{
    id: '11111111-1111-4111-8111-111111111111',
    name: 'Trip A',
    destination: 'Hanoi',
    travel_date: '2030-01-10',
    return_date: '2030-01-15',
    role: 'passenger' as const,
    access_generation: 1,
    itinerary_version: 1,
    common_document_version: 1,
    announcement_version: 1,
  }],
  next_cursor: null,
};

describe('trip repository synchronization isolation', () => {
  afterEach(() => {
    jest.clearAllMocks();
    useSessionStore.getState().clear();
  });

  it('coalesces direct refresh callers by stable account namespace and session', async () => {
    let resolveResponse!: (value: typeof tripPage) => void;
    const database = {
      getAllAsync: jest.fn().mockResolvedValue([]),
      runAsync: jest.fn().mockResolvedValue({ changes: 1 }),
    };
    mockedApiRequest.mockReturnValueOnce(new Promise((resolve) => {
      resolveResponse = resolve;
    }));
    mockedOpenDatabase.mockResolvedValue(database as never);
    useSessionStore.getState().setSession(session('a'));

    const first = refreshTrips();
    const second = refreshTrips();

    expect(second).toBe(first);
    expect(mockedApiRequest).toHaveBeenCalledTimes(1);
    resolveResponse(tripPage);
    await expect(Promise.all([first, second])).resolves.toEqual([
      expect.objectContaining({ offline: false }),
      expect.objectContaining({ offline: false }),
    ]);
    expect(mockedApiRequest).toHaveBeenCalledTimes(1);
    expect(mockedTransaction).toHaveBeenCalledTimes(1);
  });

  it('does not open Account B database when Account A response resolves after switching', async () => {
    let resolveResponse!: (value: typeof tripPage) => void;
    mockedApiRequest.mockReturnValueOnce(new Promise((resolve) => {
      resolveResponse = resolve;
    }));
    useSessionStore.getState().setSession(session('a'));
    const lease = captureSyncContext();
    const refresh = refreshTripsInContext(lease.context);
    const duplicateRefresh = refreshTripsInContext(lease.context);

    expect(duplicateRefresh).toBe(refresh);
    expect(mockedApiRequest).toHaveBeenCalledTimes(1);

    useSessionStore.getState().setSession(session('b'));
    resolveResponse(tripPage);

    await expect(refresh).rejects.toMatchObject({ code: 'SYNC_CONTEXT_CHANGED' });
    await expect(duplicateRefresh).rejects.toMatchObject({ code: 'SYNC_CONTEXT_CHANGED' });
    expect(mockedOpenDatabase).not.toHaveBeenCalled();
    expect(mockedTransaction).not.toHaveBeenCalled();
    lease.release();
  });

  it('cannot commit to an opened Account A database after switching to Account B', async () => {
    let resolveExisting!: (value: { id: string }[]) => void;
    const database = {
      getAllAsync: jest.fn(() => new Promise<{ id: string }[]>((resolve) => {
        resolveExisting = resolve;
      })),
      runAsync: jest.fn(),
    };
    mockedApiRequest.mockResolvedValueOnce(tripPage);
    mockedOpenDatabase.mockResolvedValue(database as never);
    useSessionStore.getState().setSession(session('a'));
    const lease = captureSyncContext();
    const refresh = refreshTripsInContext(lease.context);

    const rejected = expect(refresh).rejects.toMatchObject({ code: 'SYNC_CONTEXT_CHANGED' });
    await waitForCall(database.getAllAsync as jest.Mock);
    expect(mockedOpenDatabase).toHaveBeenCalledWith('agency-a.principal-a');
    useSessionStore.getState().setSession(session('b'));
    resolveExisting([]);

    await rejected;
    expect(database.runAsync).not.toHaveBeenCalled();
    lease.release();
  });

  it('stores trip-list versions as advertised without advancing applied resource state', async () => {
    const database = {
      getAllAsync: jest.fn().mockResolvedValue([]),
      runAsync: jest.fn().mockResolvedValue({ changes: 1 }),
    };
    mockedApiRequest.mockResolvedValueOnce(tripPage);
    mockedOpenDatabase.mockResolvedValue(database as never);
    useSessionStore.getState().setSession(session('a'));
    const lease = captureSyncContext();

    await expect(refreshTripsInContext(lease.context)).resolves.toMatchObject({ offline: false });

    const upsertSql = database.runAsync.mock.calls
      .map(([sql]) => String(sql))
      .find((sql) => sql.includes('INSERT INTO trips'));
    expect(upsertSql).toContain('advertised_itinerary_version');
    expect(upsertSql).toContain('advertised_common_document_version');
    expect(upsertSql).toContain('advertised_announcement_version');
    expect(upsertSql).toContain('-1, -1, -1, -1, -1, -1, -1, -1, -1');
    expect(upsertSql).not.toMatch(/\n\s+itinerary_version = excluded\.itinerary_version/);
    expect(upsertSql).not.toMatch(/\n\s+common_document_version = excluded\.common_document_version/);
    expect(upsertSql).not.toMatch(/\n\s+announcement_version = excluded\.announcement_version/);
    lease.release();
  });

  it.each([401, 403])('fails closed instead of serving stale assignments after HTTP %s', async (status) => {
    const database = {
      getAllAsync: jest.fn().mockResolvedValue(tripPage.items),
      runAsync: jest.fn(),
    };
    mockedApiRequest.mockRejectedValueOnce(
      new ApiError('Access is no longer permitted.', status, `HTTP_${status}`, null),
    );
    mockedOpenDatabase.mockResolvedValue(database as never);
    useSessionStore.getState().setSession(session('a'));
    const lease = captureSyncContext();

    await expect(refreshTripsInContext(lease.context)).rejects.toMatchObject({ status });
    expect(mockedOpenDatabase).not.toHaveBeenCalled();
    expect(mockedTransaction).not.toHaveBeenCalled();
    lease.release();
  });

  it('never exposes an expired cached trip before asynchronous purge runs', async () => {
    const database = {
      getAllAsync: jest.fn().mockResolvedValue([{
        ...tripPage.items[0],
        access_expires_at: '2020-01-01T00:00:00.000Z',
        last_server_time: '2020-01-01T00:00:00.000Z',
        advertised_itinerary_version: 1,
        advertised_common_document_version: 1,
        advertised_announcement_version: 1,
      }]),
    };
    mockedOpenDatabase.mockResolvedValue(database as never);
    useSessionStore.getState().setSession(session('a'));

    await expect(localTrips()).resolves.toEqual([]);
    expect(database.getAllAsync).toHaveBeenCalledWith(
      expect.stringContaining('MAX(cursor.last_synced_at)'),
      'agency-a.principal-a',
    );
  });
});

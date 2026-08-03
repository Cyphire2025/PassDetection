import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';
import { deleteTripVault } from '@/core/storage/vault';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

import {
  ensureTripPurgeCompleted,
  purgeTripCache,
  resetTripCache,
  retryPendingTripPurges,
  TripVaultPurgePendingError,
} from '../access-cache';

jest.mock('@/core/api/client', () => ({
  registerAccessDeniedHandler: jest.fn(() => jest.fn()),
}));
jest.mock('@/core/storage/database', () => ({
  openAccountDatabase: jest.fn(),
  withAccountTransaction: jest.fn(async (database, task) => task(database)),
}));
jest.mock('@/core/storage/vault', () => ({
  completeTripVaultPurge: jest.fn(),
  deleteTripVault: jest.fn(),
}));

const ACCOUNT = '22222222-2222-4222-8222-222222222222.33333333-3333-4333-8333-333333333333';
const TRIP_ID = '11111111-1111-4111-8111-111111111111';

type Tombstone = {
  account_namespace: string;
  trip_id: string;
  purge_epoch: number;
  blocked_access_generation: number | null;
  reason: string;
  attempt_count: number;
};

const mockedOpenDatabase = jest.mocked(openAccountDatabase);
const mockedTransaction = jest.mocked(withAccountTransaction);
const mockedDeleteTripVault = jest.mocked(deleteTripVault);

function session(): MobileSession {
  return {
    accessToken: 'access-token',
    accessTokenExpiresAt: '2030-01-01T00:00:00.000Z',
    refreshTokenExpiresAt: '2030-02-01T00:00:00.000Z',
    sessionId: 'session-id',
    networkMode: 'online',
    principal: {
      id: '44444444-4444-4444-8444-444444444444',
      accountId: '33333333-3333-4333-8333-333333333333',
      principalType: 'passenger',
      agencyId: '22222222-2222-4222-8222-222222222222',
      displayName: 'Passenger',
      email: null,
      phoneNumber: null,
      forcePasswordChange: false,
    },
  };
}

function statefulDatabase(events: string[]) {
  let tripExists = true;
  let accessExpiresAt: string | null = '2029-12-31T00:00:00.000Z';
  let tombstone: Tombstone | null = null;
  const database = {
    getFirstAsync: jest.fn(async (sql: string) => {
      if (sql.includes('SELECT access_generation FROM trips')) {
        return tripExists ? { access_generation: 7 } : null;
      }
      if (sql.includes('FROM trip_purge_tombstones')) return tombstone;
      return null;
    }),
    getAllAsync: jest.fn(async (sql: string) => {
      if (sql.includes('FROM trip_purge_tombstones')) return tombstone ? [tombstone] : [];
      return [];
    }),
    runAsync: jest.fn(async (sql: string, ...parameters: unknown[]) => {
      if (sql.includes('INSERT INTO trip_purge_tombstones')) {
        events.push('tombstone-staged');
        tombstone = {
          account_namespace: String(parameters[0]),
          trip_id: String(parameters[1]),
          purge_epoch: (tombstone?.purge_epoch ?? 0) + 1,
          blocked_access_generation: Number(parameters[2]),
          reason: String(parameters[3]),
          attempt_count: 0,
        };
      } else if (sql.includes('DELETE FROM mobile_notifications')) {
        events.push('notifications-hidden');
      } else if (sql.includes('DELETE FROM trips')) {
        events.push('trip-hidden');
        tripExists = false;
      } else if (sql.includes('UPDATE trips SET')) {
        events.push('authorized-generation-reset');
        accessExpiresAt = parameters[1] as string | null;
      } else if (sql.includes('UPDATE trip_purge_tombstones')) {
        events.push('failure-retained');
        if (tombstone) tombstone.attempt_count += 1;
      } else if (sql.includes('DELETE FROM trip_purge_tombstones')) {
        events.push('tombstone-finalized');
        const expectedEpoch = Number(parameters[2]);
        if (tombstone?.purge_epoch === expectedEpoch) tombstone = null;
      }
      return { changes: 1, lastInsertRowId: 1 };
    }),
    inspect: () => ({ tripExists, tombstone }),
    inspectExpiry: () => accessExpiresAt,
  };
  return database;
}

describe('durable trip vault purge', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useSessionStore.getState().setSession(session());
    useSelectedTripStore.getState().selectTrip(TRIP_ID);
  });

  afterEach(() => {
    useSelectedTripStore.getState().clear();
    useSessionStore.getState().clear();
  });

  it('hides registrations before vault deletion and retains a retry tombstone on failure', async () => {
    const events: string[] = [];
    const database = statefulDatabase(events);
    mockedOpenDatabase.mockResolvedValue(database as never);
    mockedDeleteTripVault.mockImplementation(async () => {
      events.push('vault-delete-failed');
      throw new Error('filesystem unavailable');
    });

    await expect(purgeTripCache(TRIP_ID, undefined, 'access_revoked')).rejects.toBeInstanceOf(
      TripVaultPurgePendingError,
    );

    expect(events).toEqual([
      'tombstone-staged',
      'notifications-hidden',
      'trip-hidden',
      'vault-delete-failed',
      'failure-retained',
    ]);
    expect(database.inspect()).toMatchObject({
      tripExists: false,
      tombstone: { reason: 'access_revoked', attempt_count: 1 },
    });
    expect(useSelectedTripStore.getState().tripId).toBeNull();
    expect(database.runAsync.mock.calls.some(([sql]) => (
      String(sql).includes('DELETE FROM pending_actions')
    ))).toBe(false);
    expect(mockedTransaction).toHaveBeenCalledTimes(2);
  });

  it('retries a retained tombstone after restart and removes it only after vault deletion succeeds', async () => {
    const events: string[] = [];
    const database = statefulDatabase(events);
    mockedOpenDatabase.mockResolvedValue(database as never);
    mockedDeleteTripVault.mockRejectedValueOnce(new Error('filesystem unavailable'));
    await expect(purgeTripCache(TRIP_ID)).rejects.toBeInstanceOf(TripVaultPurgePendingError);
    expect(database.inspect().tombstone).not.toBeNull();

    events.length = 0;
    mockedDeleteTripVault.mockImplementationOnce(async () => {
      events.push('vault-delete-succeeded');
    });
    await expect(retryPendingTripPurges()).resolves.toEqual({
      completedTripIds: [TRIP_ID],
      pendingTripIds: [],
    });

    expect(events).toEqual(['vault-delete-succeeded', 'tombstone-finalized']);
    expect(database.inspect().tombstone).toBeNull();
  });

  it('finalizes an immediate successful purge after the encrypted vault is gone', async () => {
    const events: string[] = [];
    const database = statefulDatabase(events);
    mockedOpenDatabase.mockResolvedValue(database as never);
    mockedDeleteTripVault.mockImplementation(async () => {
      events.push('vault-delete-succeeded');
    });

    await expect(purgeTripCache(TRIP_ID, undefined, 'server_removed')).resolves.toBeUndefined();

    expect(events.indexOf('trip-hidden')).toBeLessThan(events.indexOf('vault-delete-succeeded'));
    expect(events.indexOf('vault-delete-succeeded')).toBeLessThan(events.indexOf('tombstone-finalized'));
    expect(database.inspect()).toEqual({ tripExists: false, tombstone: null });
  });

  it('blocks trip synchronization while a retained purge still cannot delete the vault', async () => {
    const events: string[] = [];
    const database = statefulDatabase(events);
    mockedOpenDatabase.mockResolvedValue(database as never);
    mockedDeleteTripVault.mockRejectedValue(new Error('filesystem unavailable'));
    await expect(purgeTripCache(TRIP_ID)).rejects.toBeInstanceOf(TripVaultPurgePendingError);

    await expect(ensureTripPurgeCompleted(TRIP_ID)).rejects.toBeInstanceOf(
      TripVaultPurgePendingError,
    );
    expect(database.inspect().tombstone).not.toBeNull();
    expect(mockedDeleteTripVault).toHaveBeenCalledTimes(2);
  });

  it('preserves queued actions when a still-authorized manifest advances access generation', async () => {
    const events: string[] = [];
    const database = statefulDatabase(events);
    mockedOpenDatabase.mockResolvedValue(database as never);
    mockedDeleteTripVault.mockImplementation(async () => {
      events.push('vault-delete-succeeded');
    });

    await resetTripCache(TRIP_ID, 8, '2030-01-31T00:00:00.000Z');

    const sql = database.runAsync.mock.calls.map(([statement]) => String(statement));
    expect(sql).toContainEqual(expect.stringContaining('UPDATE trips SET'));
    expect(sql).not.toContainEqual(expect.stringContaining('DELETE FROM pending_actions'));
    expect(sql).not.toContainEqual(expect.stringContaining('DELETE FROM trips'));
    expect(database.inspect()).toEqual({ tripExists: true, tombstone: null });
    expect(database.inspectExpiry()).toBe('2030-01-31T00:00:00.000Z');
    expect(useSelectedTripStore.getState().tripId).toBe(TRIP_ID);
    expect(events.indexOf('authorized-generation-reset')).toBeLessThan(
      events.indexOf('vault-delete-succeeded'),
    );
  });

  it('retains the newly authorized finite lease across a failed purge and restart retry', async () => {
    const events: string[] = [];
    const database = statefulDatabase(events);
    mockedOpenDatabase.mockResolvedValue(database as never);
    mockedDeleteTripVault.mockRejectedValueOnce(new Error('filesystem unavailable'));

    await expect(resetTripCache(
      TRIP_ID,
      8,
      '2030-01-31T00:00:00.000Z',
    )).rejects.toBeInstanceOf(TripVaultPurgePendingError);
    expect(database.inspectExpiry()).toBe('2030-01-31T00:00:00.000Z');
    expect(database.inspect().tombstone).not.toBeNull();

    mockedDeleteTripVault.mockResolvedValueOnce(undefined);
    await retryPendingTripPurges();

    expect(database.inspectExpiry()).toBe('2030-01-31T00:00:00.000Z');
    expect(database.inspect().tombstone).toBeNull();
  });

  it('uses the immutable account namespace for the tombstone and vault deletion', async () => {
    const events: string[] = [];
    const database = statefulDatabase(events);
    mockedOpenDatabase.mockResolvedValue(database as never);
    mockedDeleteTripVault.mockResolvedValue(undefined);

    await purgeTripCache(TRIP_ID);

    expect(mockedOpenDatabase).toHaveBeenCalledWith(ACCOUNT);
    expect(mockedDeleteTripVault).toHaveBeenCalledWith(ACCOUNT, TRIP_ID);
  });
});

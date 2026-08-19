import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';
import { DEFAULT_TRIP_TIME_ZONE } from '@/core/localization/time-zone';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';

import { captureSyncContext } from '../sync-context';
import {
  promoteSnapshotStage,
  SNAPSHOT_STAGE_WRITE_BATCH_SIZE,
  stageSnapshotPage,
} from '../snapshot-rebase-store';

jest.mock('@/core/storage/database', () => ({
  openAccountDatabase: jest.fn(),
  withAccountTransaction: jest.fn(),
}));

const TRIP_ID = '11111111-1111-4111-8111-111111111111';
const AGENCY_ID = '22222222-2222-4222-8222-222222222222';
const PRINCIPAL_ID = '33333333-3333-4333-8333-333333333333';
const PASSENGER_ID = '44444444-4444-4444-8444-444444444444';
const SERVER_TIME = '2030-01-01T00:00:00.000Z';

const mockedOpenDatabase = jest.mocked(openAccountDatabase);
const mockedWithTransaction = jest.mocked(withAccountTransaction);

function session(): MobileSession {
  return {
    accessToken: 'access-token',
    accessTokenExpiresAt: '2030-01-01T01:00:00.000Z',
    refreshTokenExpiresAt: '2030-02-01T00:00:00.000Z',
    sessionId: 'session-passenger',
    networkMode: 'online',
    principal: {
      id: PRINCIPAL_ID,
      accountId: PRINCIPAL_ID,
      principalType: 'passenger',
      agencyId: AGENCY_ID,
      passengerId: PASSENGER_ID,
      displayName: 'Passenger',
      email: null,
      phoneNumber: null,
      forcePasswordChange: false,
    },
  };
}

function descriptor() {
  const trip = `/api/v1/mobile/trips/${TRIP_ID}`;
  const resourceVersions = {
    manifest: 1,
    itinerary: 0,
    common_documents: 0,
    personal_documents: 0,
    announcements: 0,
    rooming: 0,
    meals: 0,
    qr: 0,
    readiness: 0,
    roster: 0,
  };
  return {
    strategy: 'full_rebase' as const,
    trip: {
      id: TRIP_ID,
      name: 'New projection',
      destination: null,
      travel_date: null,
      return_date: null,
      timezone: DEFAULT_TRIP_TIME_ZONE,
      role: 'passenger' as const,
      access_generation: 3,
      itinerary_version: 0,
      common_document_version: 0,
      announcement_version: 0,
    },
    baseline_cursor: 100_000,
    access_generation: 3,
    server_time: SERVER_TIME,
    access_expires_at: '2030-02-01T00:00:00.000Z',
    versions: resourceVersions,
    resources: {
      manifest: `${trip}/manifest`,
      itinerary: `${trip}/itinerary`,
      announcements: `${trip}/announcements`,
      common_documents: `${trip}/common-documents`,
      personal_documents: `${trip}/documents`,
      room: `${trip}/room`,
      meals: `${trip}/meals`,
      qr: `${trip}/qr`,
      readiness: null,
      roster: null,
      attendance_sessions: null,
      sync_changes: `/api/v1/mobile/sync/changes?trip_id=${TRIP_ID}`,
      acknowledge: '/api/v1/mobile/sync/ack',
    },
    resource_counts: {
      announcements: 0,
      common_documents: 0,
      personal_documents: 0,
      roster: null,
      attendance_sessions: null,
    },
    max_incremental_changes: 10_000,
    max_group_passengers: 10_000,
    max_attendance_sessions_per_group: 10_000,
  };
}

function stagedManifest(value = descriptor()) {
  return {
    trip: value.trip,
    sync_cursor: value.baseline_cursor,
    server_time: value.server_time,
    access_expires_at: value.access_expires_at,
    versions: value.versions,
    resources: {
      itinerary: value.resources.itinerary,
      announcements: value.resources.announcements,
      common_documents: value.resources.common_documents,
      personal_documents: value.resources.personal_documents!,
      room: value.resources.room!,
      meals: value.resources.meals!,
      qr: value.resources.qr!,
      sync_changes: value.resources.sync_changes,
    },
  };
}

function installPromotionHarness(failCursorWrite = false) {
  const value = descriptor();
  const durable = { projection: 'old', cursor: 5 };
  const runOrder: string[] = [];
  const transaction = {
    getFirstAsync: jest.fn(async (sql: string) => {
      if (sql.includes('FROM trips trip')) {
        return { access_generation: 3, cursor: durable.cursor };
      }
      return null;
    }),
    getAllAsync: jest.fn(async (_sql: string, ...parameters: unknown[]) => {
      const resource = parameters[3];
      const lastIndex = Number(parameters[4]);
      if (resource === 'manifest' && lastIndex < 0) {
        return [{ item_index: 0, payload_json: JSON.stringify(stagedManifest(value)) }];
      }
      return [];
    }),
    runAsync: jest.fn(async (sql: string) => {
      if (sql.includes('UPDATE trips SET')) {
        runOrder.push('projection');
        durable.projection = 'new';
      } else if (sql.includes('INSERT INTO sync_cursors')) {
        runOrder.push('cursor');
        if (failCursorWrite) throw new Error('cursor write failed');
        durable.cursor = value.baseline_cursor;
      } else if (sql.includes('DELETE FROM sync_rebase_staging')) {
        runOrder.push('stage-delete');
      }
      return { changes: 1, lastInsertRowId: 1 };
    }),
  };
  const database = {};
  mockedOpenDatabase.mockResolvedValue(database as never);
  mockedWithTransaction.mockImplementation(async (received, operation) => {
    expect(received).toBe(database);
    const before = { ...durable };
    try {
      await operation(transaction as never);
    } catch (error) {
      durable.projection = before.projection;
      durable.cursor = before.cursor;
      throw error;
    }
  });
  return { durable, runOrder, value };
}

beforeEach(() => {
  jest.clearAllMocks();
  useSessionStore.getState().setSession(session());
});

afterEach(() => {
  useSessionStore.getState().clear();
});

test('promotes metadata, S2 versions, and baseline cursor in one transaction', async () => {
  const harness = installPromotionHarness();
  const lease = captureSyncContext();
  try {
    await expect(promoteSnapshotStage({
      generationId: '55555555-5555-4555-8555-555555555555',
      namespace: `${AGENCY_ID}.${PRINCIPAL_ID}`,
      tripId: TRIP_ID,
    }, harness.value, lease.context)).resolves.toBeUndefined();
  } finally {
    lease.release();
  }

  expect(mockedWithTransaction).toHaveBeenCalledTimes(1);
  expect(harness.durable).toEqual({ projection: 'new', cursor: 100_000 });
  expect(harness.runOrder.slice(-3)).toEqual(['projection', 'cursor', 'stage-delete']);
});

test('cursor failure rolls the replacement projection back to the prior generation', async () => {
  const harness = installPromotionHarness(true);
  const lease = captureSyncContext();
  try {
    await expect(promoteSnapshotStage({
      generationId: '55555555-5555-4555-8555-555555555555',
      namespace: `${AGENCY_ID}.${PRINCIPAL_ID}`,
      tripId: TRIP_ID,
    }, harness.value, lease.context)).rejects.toThrow('cursor write failed');
  } finally {
    lease.release();
  }

  expect(mockedWithTransaction).toHaveBeenCalledTimes(1);
  expect(harness.durable).toEqual({ projection: 'old', cursor: 5 });
  expect(harness.runOrder).not.toContain('stage-delete');
});

test('stages snapshot pages in bounded multi-row statements below SQLite limits', async () => {
  const database = {};
  const transaction = {
    runAsync: jest.fn(async (_sql: string, parameters: unknown[]) => ({
      changes: parameters.length / 7,
      lastInsertRowId: 1,
    })),
  };
  mockedOpenDatabase.mockResolvedValue(database as never);
  mockedWithTransaction.mockImplementation(async (received, operation) => {
    expect(received).toBe(database);
    await operation(transaction as never);
  });
  const items = Array.from(
    { length: (SNAPSHOT_STAGE_WRITE_BATCH_SIZE * 2) + 5 },
    (_, index) => ({ key: `item-${index}`, payload: { id: `item-${index}` } }),
  );
  const lease = captureSyncContext();
  try {
    await expect(stageSnapshotPage({
      generationId: '55555555-5555-4555-8555-555555555555',
      namespace: `${AGENCY_ID}.${PRINCIPAL_ID}`,
      tripId: TRIP_ID,
    }, 'announcements', 0, items, lease.context)).resolves.toBe(items.length);
  } finally {
    lease.release();
  }

  expect(mockedWithTransaction).toHaveBeenCalledTimes(1);
  expect(transaction.runAsync).toHaveBeenCalledTimes(3);
  expect(transaction.runAsync.mock.calls.map(([, parameters]) => parameters.length)).toEqual([
    SNAPSHOT_STAGE_WRITE_BATCH_SIZE * 7,
    SNAPSHOT_STAGE_WRITE_BATCH_SIZE * 7,
    5 * 7,
  ]);
  expect(transaction.runAsync.mock.calls.every(([, parameters]) => parameters.length <= 700)).toBe(true);
});

test('rolls every page batch back when a later bounded staging statement fails', async () => {
  const database = {};
  let durableRows = 0;
  let calls = 0;
  const transaction = {
    runAsync: jest.fn(async (_sql: string, parameters: unknown[]) => {
      calls += 1;
      durableRows += parameters.length / 7;
      if (calls === 2) throw new Error('staging write failed');
      return { changes: parameters.length / 7, lastInsertRowId: 1 };
    }),
  };
  mockedOpenDatabase.mockResolvedValue(database as never);
  mockedWithTransaction.mockImplementation(async (_received, operation) => {
    const before = durableRows;
    try {
      await operation(transaction as never);
    } catch (error) {
      durableRows = before;
      throw error;
    }
  });
  const items = Array.from(
    { length: SNAPSHOT_STAGE_WRITE_BATCH_SIZE + 1 },
    (_, index) => ({ key: `item-${index}`, payload: { id: `item-${index}` } }),
  );
  const lease = captureSyncContext();
  try {
    await expect(stageSnapshotPage({
      generationId: '55555555-5555-4555-8555-555555555555',
      namespace: `${AGENCY_ID}.${PRINCIPAL_ID}`,
      tripId: TRIP_ID,
    }, 'announcements', 0, items, lease.context)).rejects.toThrow('staging write failed');
  } finally {
    lease.release();
  }
  expect(durableRows).toBe(0);
});

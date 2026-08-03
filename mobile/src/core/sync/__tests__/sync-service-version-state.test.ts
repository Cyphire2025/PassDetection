import { apiRequest } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import type { MobileRole, MobileSession } from '@/core/auth/types';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';
import {
  loadMeal,
  loadReadiness,
  loadRoom,
  prefetchCommonOfflineDocuments,
  prefetchPassengerOfflineDocuments,
  refreshAnnouncements,
  refreshCommonDocuments,
  refreshDocuments,
  refreshQr,
} from '@/features/content/data/content-repository';
import { refreshItinerary } from '@/features/content/data/itinerary-repository';
import { drainAttendanceQueue } from '@/features/coordinator/data/attendance-queue';
import {
  applyCoordinatorPassengerChanges,
  loadAttendanceSummary,
  syncFullRoster,
} from '@/features/coordinator/data/coordinator-repository';
import { drainIncidentQueue } from '@/features/coordinator/data/operations-repository';
import { drainNotificationReads } from '@/features/notifications/data/notification-repository';
import {
  localTripsInContext,
  refreshTripsInContext,
} from '@/features/trips/data/trip-repository';
import type { Trip } from '@/features/trips/model/trip';

import { syncAllTripsWithSummary, syncTrip } from '../sync-service';

jest.mock('@/core/api/client', () => {
  const actual = jest.requireActual('@/core/api/client');
  return { ...actual, apiRequest: jest.fn() };
});
jest.mock('@/core/storage/database', () => ({
  openAccountDatabase: jest.fn(),
  withAccountTransaction: jest.fn(),
}));
jest.mock('@/features/content/data/content-repository', () => ({
  loadMeal: jest.fn(),
  loadReadiness: jest.fn(),
  loadRoom: jest.fn(),
  prefetchCommonOfflineDocuments: jest.fn(),
  prefetchPassengerOfflineDocuments: jest.fn(),
  refreshAnnouncements: jest.fn(),
  refreshCommonDocuments: jest.fn(),
  refreshDocuments: jest.fn(),
  refreshQr: jest.fn(),
}));
jest.mock('@/features/content/data/itinerary-repository', () => ({
  refreshItinerary: jest.fn(),
}));
jest.mock('@/features/coordinator/data/attendance-queue', () => ({
  drainAttendanceQueue: jest.fn(),
}));
jest.mock('@/features/coordinator/data/coordinator-repository', () => ({
  applyCoordinatorPassengerChanges: jest.fn(),
  loadAttendanceSummary: jest.fn(),
  syncFullRoster: jest.fn(),
}));
jest.mock('@/features/coordinator/data/operations-repository', () => ({
  drainIncidentQueue: jest.fn(),
}));
jest.mock('@/features/notifications/data/notification-repository', () => ({
  drainNotificationReads: jest.fn(),
}));
jest.mock('@/features/trips/data/trip-repository', () => ({
  localTripsInContext: jest.fn(),
  refreshTripsInContext: jest.fn(),
}));
jest.mock('../access-cache', () => ({
  ensureTripPurgeCompleted: jest.fn(),
  purgeTripCache: jest.fn(),
  resetTripCache: jest.fn(),
}));

type Versions = {
  itinerary: number;
  commonDocuments: number;
  personalDocuments: number;
  announcements: number;
  readiness: number;
  roster: number;
  rooming: number;
  meals: number;
  qr: number;
};

type DurableState = {
  accessGeneration: number;
  applied: Versions;
  advertised: Versions;
  cursor: number | null;
};

const TRIP_ID = '11111111-1111-4111-8111-111111111111';
const AGENCY_ID = '22222222-2222-4222-8222-222222222222';
const PRINCIPAL_ID = '33333333-3333-4333-8333-333333333333';
const SERVER_TIME = '2030-01-01T00:00:00.000Z';

const mockedApiRequest = jest.mocked(apiRequest);
const mockedOpenDatabase = jest.mocked(openAccountDatabase);
const mockedWithTransaction = jest.mocked(withAccountTransaction);
const mockedItinerary = jest.mocked(refreshItinerary);
const mockedAnnouncements = jest.mocked(refreshAnnouncements);
const mockedCommonDocuments = jest.mocked(refreshCommonDocuments);
const mockedPersonalDocuments = jest.mocked(refreshDocuments);
const mockedRoom = jest.mocked(loadRoom);
const mockedMeal = jest.mocked(loadMeal);
const mockedQr = jest.mocked(refreshQr);
const mockedReadiness = jest.mocked(loadReadiness);
const mockedRoster = jest.mocked(syncFullRoster);
const mockedPassengerChanges = jest.mocked(applyCoordinatorPassengerChanges);
const mockedAttendance = jest.mocked(loadAttendanceSummary);
const mockedPassengerPrefetch = jest.mocked(prefetchPassengerOfflineDocuments);
const mockedCommonPrefetch = jest.mocked(prefetchCommonOfflineDocuments);
const mockedLocalTrips = jest.mocked(localTripsInContext);
const mockedRefreshTrips = jest.mocked(refreshTripsInContext);

function versions(value: number): Versions {
  return {
    itinerary: value,
    commonDocuments: value,
    personalDocuments: value,
    announcements: value,
    readiness: value,
    roster: value,
    rooming: value,
    meals: value,
    qr: value,
  };
}

function session(role: MobileRole): MobileSession {
  return {
    accessToken: 'access-token',
    accessTokenExpiresAt: '2030-01-01T01:00:00.000Z',
    refreshTokenExpiresAt: '2030-02-01T00:00:00.000Z',
    sessionId: `session-${role}`,
    networkMode: 'online',
    principal: {
      id: PRINCIPAL_ID,
      accountId: PRINCIPAL_ID,
      principalType: role,
      agencyId: AGENCY_ID,
      displayName: 'Test principal',
      email: null,
      phoneNumber: null,
      forcePasswordChange: false,
    },
  };
}

function manifest(role: MobileRole, value = 2, tripId = TRIP_ID) {
  return {
    trip: {
      id: tripId,
      name: 'Enterprise trip',
      destination: 'Singapore',
      travel_date: '2030-01-10',
      return_date: '2030-01-15',
      role,
      access_generation: 1,
      itinerary_version: value,
      common_document_version: value,
      announcement_version: value,
    },
    sync_cursor: 2,
    server_time: SERVER_TIME,
    access_expires_at: '2030-01-31T00:00:00.000Z',
    versions: {
      manifest: value,
      itinerary: value,
      common_documents: value,
      personal_documents: value,
      announcements: value,
      rooming: value,
      meals: value,
      qr: value,
      readiness: value,
      roster: value,
    },
    resources: {
      itinerary: `/api/v1/mobile/trips/${tripId}/itinerary`,
      announcements: `/api/v1/mobile/trips/${tripId}/announcements`,
      common_documents: `/api/v1/mobile/trips/${tripId}/common-documents`,
      personal_documents: `/api/v1/mobile/trips/${tripId}/documents`,
      room: `/api/v1/mobile/trips/${tripId}/room`,
      meals: `/api/v1/mobile/trips/${tripId}/meals`,
      qr: `/api/v1/mobile/trips/${tripId}/qr`,
      sync_changes: '/api/v1/mobile/sync/changes',
    },
  };
}

function installHarness(role: MobileRole) {
  const state: DurableState = {
    accessGeneration: 1,
    applied: versions(1),
    advertised: versions(1),
    cursor: 1,
  };
  let failCursorWrite = false;

  const database = {
    getFirstAsync: jest.fn(async (sql: string) => {
      if (sql.includes('FROM trips WHERE')) {
        return {
          access_generation: state.accessGeneration,
          itinerary_version: state.applied.itinerary,
          common_document_version: state.applied.commonDocuments,
          personal_document_version: state.applied.personalDocuments,
          announcement_version: state.applied.announcements,
          readiness_version: state.applied.readiness,
          roster_version: state.applied.roster,
          rooming_version: state.applied.rooming,
          meals_version: state.applied.meals,
          qr_version: state.applied.qr,
        };
      }
      if (sql.includes('FROM sync_cursors')) {
        return state.cursor === null ? null : { cursor: state.cursor };
      }
      return null;
    }),
    runAsync: jest.fn(async (sql: string, ...parameters: unknown[]) => {
      if (sql.includes('INSERT INTO trips')) {
        state.accessGeneration = Number(parameters[8]);
        state.advertised = {
          itinerary: Number(parameters[10]),
          commonDocuments: Number(parameters[11]),
          personalDocuments: Number(parameters[12]),
          announcements: Number(parameters[13]),
          readiness: Number(parameters[14]),
          roster: Number(parameters[15]),
          rooming: Number(parameters[16]),
          meals: Number(parameters[17]),
          qr: Number(parameters[18]),
        };
      }
      return { changes: 1, lastInsertRowId: 1 };
    }),
  };

  const transaction = {
    runAsync: jest.fn(async (sql: string, ...parameters: unknown[]) => {
      if (sql.includes('UPDATE trips SET') && sql.includes('advertised_itinerary_version')) {
        const expectedAdvertised = parameters.slice(12, 21).map(Number);
        const actualAdvertised = Object.values(state.advertised);
        if (
          parameters[9] !== `${AGENCY_ID}.${PRINCIPAL_ID}` ||
          parameters[10] !== TRIP_ID ||
          Number(parameters[11]) !== state.accessGeneration ||
          expectedAdvertised.some((value, index) => value !== actualAdvertised[index])
        ) {
          return { changes: 0, lastInsertRowId: 0 };
        }
        state.applied = {
          itinerary: Number(parameters[0]),
          commonDocuments: Number(parameters[1]),
          personalDocuments: Number(parameters[2]),
          announcements: Number(parameters[3]),
          readiness: Number(parameters[4]),
          roster: Number(parameters[5]),
          rooming: Number(parameters[6]),
          meals: Number(parameters[7]),
          qr: Number(parameters[8]),
        };
      } else if (sql.includes('INSERT INTO sync_cursors')) {
        if (failCursorWrite) throw new Error('cursor write failed');
        state.cursor = Number(parameters[2]);
      }
      return { changes: 1, lastInsertRowId: 1 };
    }),
  };

  mockedOpenDatabase.mockResolvedValue(database as never);
  mockedWithTransaction.mockImplementation(async (received, task) => {
    expect(received).toBe(database);
    const snapshot: DurableState = {
      accessGeneration: state.accessGeneration,
      applied: { ...state.applied },
      advertised: { ...state.advertised },
      cursor: state.cursor,
    };
    try {
      await task(transaction as never);
    } catch (error) {
      state.accessGeneration = snapshot.accessGeneration;
      state.applied = snapshot.applied;
      state.advertised = snapshot.advertised;
      state.cursor = snapshot.cursor;
      throw error;
    }
  });

  const nextManifest = manifest(role);
  mockedApiRequest.mockImplementation(async (path: string) => {
    if (path === `/mobile/trips/${TRIP_ID}/manifest`) return nextManifest as never;
    if (path.startsWith('/mobile/sync/changes?')) {
      return { changes: [], next_cursor: 2, has_more: false } as never;
    }
    if (path === '/mobile/sync/ack') {
      return {
        trip_id: TRIP_ID,
        cursor: 2,
        access_generation: 1,
        acknowledged_at: SERVER_TIME,
      } as never;
    }
    throw new Error(`Unexpected API path: ${path}`);
  });
  useSessionStore.getState().setSession(session(role));

  return {
    database,
    state,
    setCursorWriteFailure(value: boolean) {
      failCursorWrite = value;
    },
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  useSessionStore.getState().clear();
  for (const mock of [
    mockedItinerary,
    mockedAnnouncements,
    mockedCommonDocuments,
    mockedPersonalDocuments,
    mockedRoom,
    mockedMeal,
    mockedQr,
    mockedReadiness,
    mockedRoster,
    mockedPassengerChanges,
    mockedAttendance,
    jest.mocked(drainAttendanceQueue),
    jest.mocked(drainIncidentQueue),
    jest.mocked(drainNotificationReads),
  ]) {
    mock.mockResolvedValue(undefined as never);
  }
  mockedPassengerPrefetch.mockResolvedValue({
    total: 0,
    completed: 0,
    failed: 0,
    currentDocumentName: null,
  });
  mockedCommonPrefetch.mockResolvedValue({
    total: 0,
    completed: 0,
    failed: 0,
    currentDocumentName: null,
  });
  mockedLocalTrips.mockResolvedValue([]);
  mockedRefreshTrips.mockResolvedValue({ trips: [], offline: false });
});

afterEach(() => {
  useSessionStore.getState().clear();
});

test('empty-journal passenger v1 to v2 refreshes every passenger resource before atomic finalization', async () => {
  const harness = installHarness('passenger');

  await expect(syncTrip(TRIP_ID)).resolves.toMatchObject({ cursor: 2, changed: true });

  expect(mockedItinerary).toHaveBeenCalledTimes(1);
  expect(mockedAnnouncements).toHaveBeenCalledTimes(1);
  expect(mockedCommonDocuments).toHaveBeenCalledTimes(1);
  expect(mockedPersonalDocuments).toHaveBeenCalledTimes(1);
  expect(mockedRoom).toHaveBeenCalledTimes(1);
  expect(mockedMeal).toHaveBeenCalledTimes(1);
  expect(mockedQr).toHaveBeenCalledTimes(1);
  expect(mockedPassengerPrefetch).toHaveBeenCalledTimes(1);
  expect(harness.state.applied).toEqual(versions(2));
  expect(harness.state.advertised).toEqual(versions(2));
  expect(harness.state.cursor).toBe(2);

  const manifestSql = harness.database.runAsync.mock.calls.find(([sql]) =>
    String(sql).includes('INSERT INTO trips'))?.[0];
  expect(manifestSql).toContain(
    'advertised_itinerary_version = excluded.advertised_itinerary_version',
  );
  expect(manifestSql).not.toMatch(/\n\s+itinerary_version = excluded\.itinerary_version/);
});

test('empty-journal manager and coordinator versions refresh their role-specific resources', async () => {
  installHarness('client_manager');
  await syncTrip(TRIP_ID);
  expect(mockedItinerary).toHaveBeenCalledTimes(1);
  expect(mockedCommonDocuments).toHaveBeenCalledTimes(1);
  expect(mockedAnnouncements).toHaveBeenCalledTimes(1);
  expect(mockedReadiness).toHaveBeenCalledTimes(1);

  jest.clearAllMocks();
  useSessionStore.getState().clear();
  installHarness('coordinator');
  mockedRoster.mockResolvedValue(undefined as never);
  mockedAttendance.mockResolvedValue(undefined as never);
  jest.mocked(drainAttendanceQueue).mockResolvedValue(undefined);
  jest.mocked(drainIncidentQueue).mockResolvedValue(undefined);
  jest.mocked(drainNotificationReads).mockResolvedValue(undefined);
  await syncTrip(TRIP_ID);
  expect(mockedItinerary).toHaveBeenCalledTimes(1);
  expect(mockedCommonDocuments).toHaveBeenCalledTimes(1);
  expect(mockedAnnouncements).toHaveBeenCalledTimes(1);
  expect(mockedRoster).toHaveBeenCalledTimes(1);
  expect(mockedAttendance).toHaveBeenCalledTimes(1);
});

test('verified coordinator passenger delta avoids replacing a 1,500-passenger roster', async () => {
  const harness = installHarness('coordinator');
  const targetedManifest = manifest('coordinator', 1);
  targetedManifest.sync_cursor = 2;
  targetedManifest.versions.roster = 2;
  mockedApiRequest.mockImplementation(async (path: string) => {
    if (path === `/mobile/trips/${TRIP_ID}/manifest`) return targetedManifest as never;
    if (path.startsWith('/mobile/sync/changes?')) {
      return {
        changes: [
          {
            sequence: 2,
            group_id: TRIP_ID,
            entity_type: 'coordinator_passenger',
            entity_id: PRINCIPAL_ID,
            operation: 'upsert',
            version: 2,
            occurred_at: SERVER_TIME,
            payload: {
              resource_path: `/api/v1/mobile/coordinator/groups/${TRIP_ID}/passengers/${PRINCIPAL_ID}`,
              roster_revision: 2,
            },
          },
        ],
        next_cursor: 2,
        has_more: false,
      } as never;
    }
    if (path === '/mobile/sync/ack') {
      return {
        trip_id: TRIP_ID,
        cursor: 2,
        access_generation: 1,
        acknowledged_at: SERVER_TIME,
      } as never;
    }
    throw new Error(`Unexpected API path: ${path}`);
  });

  await expect(syncTrip(TRIP_ID)).resolves.toMatchObject({ cursor: 2, changed: true });

  expect(mockedPassengerChanges).toHaveBeenCalledWith(
    TRIP_ID,
    [{ passengerId: PRINCIPAL_ID, operation: 'upsert' }],
    expect.objectContaining({ role: 'coordinator' }),
  );
  expect(mockedRoster).not.toHaveBeenCalled();
  expect(mockedAttendance).toHaveBeenCalledTimes(1);
  expect(harness.state.applied.roster).toBe(2);
});

test('unverified coordinator passenger delta fails closed to full roster reconciliation', async () => {
  installHarness('coordinator');
  const targetedManifest = manifest('coordinator', 1);
  targetedManifest.sync_cursor = 2;
  targetedManifest.versions.roster = 2;
  mockedApiRequest.mockImplementation(async (path: string) => {
    if (path === `/mobile/trips/${TRIP_ID}/manifest`) return targetedManifest as never;
    if (path.startsWith('/mobile/sync/changes?')) {
      return {
        changes: [
          {
            sequence: 2,
            group_id: TRIP_ID,
            entity_type: 'coordinator_passenger',
            entity_id: PRINCIPAL_ID,
            operation: 'upsert',
            version: 2,
            occurred_at: SERVER_TIME,
            payload: { roster_revision: 999 },
          },
        ],
        next_cursor: 2,
        has_more: false,
      } as never;
    }
    if (path === '/mobile/sync/ack') {
      return {
        trip_id: TRIP_ID,
        cursor: 2,
        access_generation: 1,
        acknowledged_at: SERVER_TIME,
      } as never;
    }
    throw new Error(`Unexpected API path: ${path}`);
  });

  await syncTrip(TRIP_ID);

  expect(mockedRoster).toHaveBeenCalledTimes(1);
  expect(mockedPassengerChanges).not.toHaveBeenCalled();
});

type ResourceFailureCase = Readonly<{
  role: MobileRole;
  resource: string;
  failOnce: (error: Error) => void;
  calls: () => number;
}>;

const resourceFailureCases: ResourceFailureCase[] = [
  ...(['passenger', 'client_manager', 'coordinator'] as MobileRole[]).flatMap((role) => [
    {
      role,
      resource: 'itinerary',
      failOnce: (error: Error) => mockedItinerary.mockRejectedValueOnce(error),
      calls: () => mockedItinerary.mock.calls.length,
    },
    {
      role,
      resource: 'announcements',
      failOnce: (error: Error) => mockedAnnouncements.mockRejectedValueOnce(error),
      calls: () => mockedAnnouncements.mock.calls.length,
    },
    {
      role,
      resource: 'common documents',
      failOnce: (error: Error) => mockedCommonDocuments.mockRejectedValueOnce(error),
      calls: () => mockedCommonDocuments.mock.calls.length,
    },
  ]),
  {
    role: 'passenger',
    resource: 'personal documents',
    failOnce: (error) => mockedPersonalDocuments.mockRejectedValueOnce(error),
    calls: () => mockedPersonalDocuments.mock.calls.length,
  },
  {
    role: 'passenger',
    resource: 'room',
    failOnce: (error) => mockedRoom.mockRejectedValueOnce(error),
    calls: () => mockedRoom.mock.calls.length,
  },
  {
    role: 'passenger',
    resource: 'meals',
    failOnce: (error) => mockedMeal.mockRejectedValueOnce(error),
    calls: () => mockedMeal.mock.calls.length,
  },
  {
    role: 'passenger',
    resource: 'QR',
    failOnce: (error) => mockedQr.mockRejectedValueOnce(error),
    calls: () => mockedQr.mock.calls.length,
  },
  {
    role: 'passenger',
    resource: 'offline document prefetch',
    failOnce: (error) => mockedPassengerPrefetch.mockRejectedValueOnce(error),
    calls: () => mockedPassengerPrefetch.mock.calls.length,
  },
  {
    role: 'client_manager',
    resource: 'readiness',
    failOnce: (error) => mockedReadiness.mockRejectedValueOnce(error),
    calls: () => mockedReadiness.mock.calls.length,
  },
  {
    role: 'coordinator',
    resource: 'roster',
    failOnce: (error) => mockedRoster.mockRejectedValueOnce(error),
    calls: () => mockedRoster.mock.calls.length,
  },
  {
    role: 'coordinator',
    resource: 'attendance',
    failOnce: (error) => mockedAttendance.mockRejectedValueOnce(error),
    calls: () => mockedAttendance.mock.calls.length,
  },
];

test.each(resourceFailureCases)(
  '$role $resource failure leaves versions unapplied and retry reconciles it',
  async ({ role, resource, failOnce, calls }) => {
    const harness = installHarness(role);
    const failure = new Error(`temporary ${resource} failure`);
    failOnce(failure);

    await expect(syncTrip(TRIP_ID)).rejects.toThrow(failure.message);
    expect(harness.state.advertised).toEqual(versions(2));
    expect(harness.state.applied).toEqual(versions(1));
    expect(harness.state.cursor).toBe(1);

    await expect(syncTrip(TRIP_ID)).resolves.toMatchObject({ cursor: 2 });
    expect(calls()).toBe(2);
    expect(harness.state.applied).toEqual(versions(2));
    expect(harness.state.cursor).toBe(2);
  },
);

test.each(['passenger', 'client_manager', 'coordinator'] as MobileRole[])(
  '%s partial offline document outcome advances metadata cursor and retries only the job',
  async (role) => {
    const harness = installHarness(role);
    const prefetch = role === 'passenger' ? mockedPassengerPrefetch : mockedCommonPrefetch;
    prefetch
      .mockResolvedValueOnce({
        total: 1,
        completed: 0,
        failed: 1,
        currentDocumentName: null,
      })
      .mockResolvedValueOnce({
        total: 1,
        completed: 1,
        failed: 0,
        currentDocumentName: null,
      });

    await expect(syncTrip(TRIP_ID)).resolves.toMatchObject({
      cursor: 2,
      documentPrefetch: { total: 1, completed: 0, failed: 1 },
    });
    expect(harness.state.advertised).toEqual(versions(2));
    expect(harness.state.applied).toEqual(versions(2));
    expect(harness.state.cursor).toBe(2);

    await expect(syncTrip(TRIP_ID)).resolves.toMatchObject({ cursor: 2 });
    expect(prefetch).toHaveBeenCalledTimes(2);
    // Resource metadata was finalized on the first pass, so the second pass
    // does not replay its page merely because one encrypted blob failed.
    expect(mockedPersonalDocuments).toHaveBeenCalledTimes(role === 'passenger' ? 1 : 0);
    expect(mockedCommonDocuments).toHaveBeenCalledTimes(1);
    expect(harness.state.applied).toEqual(versions(2));
    expect(harness.state.cursor).toBe(2);
  },
);

test.each(['passenger', 'client_manager', 'coordinator'] as MobileRole[])(
  '%s cursor write failure rolls back applied versions and remains retryable',
  async (role) => {
  const harness = installHarness(role);
  harness.setCursorWriteFailure(true);

  await expect(syncTrip(TRIP_ID)).rejects.toThrow('cursor write failed');
  expect(harness.state.advertised).toEqual(versions(2));
  expect(harness.state.applied).toEqual(versions(1));
  expect(harness.state.cursor).toBe(1);

  harness.setCursorWriteFailure(false);
  await expect(syncTrip(TRIP_ID)).resolves.toMatchObject({ cursor: 2 });
  expect(mockedItinerary).toHaveBeenCalledTimes(2);
  expect(harness.state.applied).toEqual(versions(2));
  expect(harness.state.cursor).toBe(2);
  },
);

async function waitForCondition(predicate: () => boolean): Promise<void> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  throw new Error('The expected asynchronous state was not reached.');
}

function assignedTrips(count: number): Trip[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `11111111-1111-4111-8111-${String(index + 1).padStart(12, '0')}`,
    name: `Trip ${index + 1}`,
    destination: 'Singapore',
    travelDate: '2030-01-10',
    returnDate: '2030-01-15',
    role: 'passenger',
    accessGeneration: 1,
    accessExpiresAt: '2030-01-31T00:00:00.000Z',
    itineraryVersion: 1,
    commonDocumentVersion: 1,
    announcementVersion: 1,
    updatedAt: SERVER_TIME,
  }));
}

function installFullSyncDatabase() {
  const database = {
    getFirstAsync: jest.fn(async (sql: string) => {
      if (sql.includes('FROM trips WHERE')) {
        return {
          access_generation: 1,
          itinerary_version: 1,
          common_document_version: 1,
          personal_document_version: 1,
          announcement_version: 1,
          readiness_version: 1,
          roster_version: 1,
          rooming_version: 1,
          meals_version: 1,
          qr_version: 1,
        };
      }
      if (sql.includes('FROM sync_cursors')) return { cursor: 1 };
      return null;
    }),
    runAsync: jest.fn(async () => ({ changes: 1, lastInsertRowId: 1 })),
  };
  const transaction = {
    runAsync: jest.fn(async () => ({ changes: 1, lastInsertRowId: 1 })),
  };
  mockedOpenDatabase.mockResolvedValue(database as never);
  mockedWithTransaction.mockImplementation(async (_received, task) => {
    await task(transaction as never);
  });
  return { database, transaction };
}

test('coalesces concurrent full sync requests for the same account and session', async () => {
  useSessionStore.getState().setSession(session('passenger'));
  mockedLocalTrips.mockResolvedValue([]);
  let resolveTrips!: (value: { trips: Trip[]; offline: boolean }) => void;
  mockedRefreshTrips.mockReturnValue(new Promise((resolve) => {
    resolveTrips = resolve;
  }));

  const first = syncAllTripsWithSummary();
  const second = syncAllTripsWithSummary();

  expect(second).toBe(first);
  await waitForCondition(() => mockedRefreshTrips.mock.calls.length === 1);
  resolveTrips({ trips: [], offline: false });
  await expect(Promise.all([first, second])).resolves.toEqual([
    {
      results: [],
      failures: [],
      requestedTripCount: 0,
      tripsChanged: false,
      removedTripIds: [],
    },
    {
      results: [],
      failures: [],
      requestedTripCount: 0,
      tripsChanged: false,
      removedTripIds: [],
    },
  ]);
  expect(mockedRefreshTrips).toHaveBeenCalledTimes(1);
});

test('full sync uses a bounded two-worker pool and preserves assigned-trip result order', async () => {
  const trips = assignedTrips(5);
  installFullSyncDatabase();
  useSessionStore.getState().setSession(session('passenger'));
  mockedLocalTrips.mockResolvedValue(trips);
  mockedRefreshTrips.mockResolvedValue({ trips, offline: false });

  let activeManifests = 0;
  let maximumActiveManifests = 0;
  let startedManifests = 0;
  const releaseManifest: (() => void)[] = [];
  mockedApiRequest.mockImplementation((path: string, options?: { body?: unknown }) => {
    const match = /^\/mobile\/trips\/([^/]+)\/manifest$/.exec(path);
    if (match?.[1]) {
      const tripId = match[1];
      startedManifests += 1;
      activeManifests += 1;
      maximumActiveManifests = Math.max(maximumActiveManifests, activeManifests);
      return new Promise((resolve) => {
        releaseManifest.push(() => {
          activeManifests -= 1;
          resolve(manifest('passenger', 1, tripId));
        });
      }) as never;
    }
    if (path.startsWith('/mobile/sync/changes?')) {
      return Promise.resolve({ changes: [], next_cursor: 1, has_more: false }) as never;
    }
    if (path === '/mobile/sync/ack') {
      const body = options?.body as { trip_id: string };
      return Promise.resolve({
        trip_id: body.trip_id,
        cursor: 1,
        access_generation: 1,
        acknowledged_at: SERVER_TIME,
      }) as never;
    }
    return Promise.reject(new Error(`Unexpected API path: ${path}`)) as never;
  });

  const syncing = syncAllTripsWithSummary();
  await waitForCondition(() => startedManifests === 2);
  expect(maximumActiveManifests).toBe(2);
  releaseManifest.splice(0).forEach((release) => release());
  await waitForCondition(() => startedManifests === 4);
  expect(maximumActiveManifests).toBe(2);
  releaseManifest.splice(0).forEach((release) => release());
  await waitForCondition(() => startedManifests === 5);
  releaseManifest.splice(0).forEach((release) => release());

  const result = await syncing;
  expect(maximumActiveManifests).toBe(2);
  expect(result.results.map((item) => item.tripId)).toEqual(trips.map((trip) => trip.id));
  expect(result.failures).toEqual([]);
  expect(result.requestedTripCount).toBe(trips.length);
});

test('full sync reports ordered per-trip failures when every assigned trip fails', async () => {
  const trips = assignedTrips(3);
  installFullSyncDatabase();
  useSessionStore.getState().setSession(session('passenger'));
  mockedLocalTrips.mockResolvedValue(trips);
  mockedRefreshTrips.mockResolvedValue({ trips, offline: false });
  mockedApiRequest.mockRejectedValue(new TypeError('network request failed'));

  const summary = await syncAllTripsWithSummary();

  expect(summary.results).toEqual([]);
  expect(summary.requestedTripCount).toBe(3);
  expect(summary.failures).toEqual(trips.map((trip) => ({
    tripId: trip.id,
    category: 'network',
    retryable: true,
    code: 'SYNC_NETWORK',
  })));
});

test('full sync preserves successes and a retryable PII-free partial failure', async () => {
  const trips = assignedTrips(2);
  installFullSyncDatabase();
  useSessionStore.getState().setSession(session('passenger'));
  mockedLocalTrips.mockResolvedValue(trips);
  mockedRefreshTrips.mockResolvedValue({ trips, offline: false });
  mockedApiRequest.mockImplementation((path: string, options?: { body?: unknown }) => {
    if (path === `/mobile/trips/${trips[0]!.id}/manifest`) {
      return Promise.reject(new TypeError('private provider detail must not escape')) as never;
    }
    if (path === `/mobile/trips/${trips[1]!.id}/manifest`) {
      return Promise.resolve(manifest('passenger', 1, trips[1]!.id)) as never;
    }
    if (path.startsWith('/mobile/sync/changes?')) {
      return Promise.resolve({ changes: [], next_cursor: 1, has_more: false }) as never;
    }
    if (path === '/mobile/sync/ack') {
      const body = options?.body as { trip_id: string };
      return Promise.resolve({
        trip_id: body.trip_id,
        cursor: 1,
        access_generation: 1,
        acknowledged_at: SERVER_TIME,
      }) as never;
    }
    return Promise.reject(new Error(`Unexpected API path: ${path}`)) as never;
  });

  const summary = await syncAllTripsWithSummary();

  expect(summary.results.map((result) => result.tripId)).toEqual([trips[1]!.id]);
  expect(summary.failures).toEqual([{
    tripId: trips[0]!.id,
    category: 'network',
    retryable: true,
    code: 'SYNC_NETWORK',
  }]);
  expect(JSON.stringify(summary)).not.toContain('private provider detail');
});

test('same-session passenger identity switch cancels the old pool before queued trips begin', async () => {
  const trips = assignedTrips(5);
  installFullSyncDatabase();
  useSessionStore.getState().setSession(session('passenger'));
  mockedLocalTrips.mockResolvedValue(trips);
  mockedRefreshTrips.mockResolvedValue({ trips, offline: false });

  let startedManifests = 0;
  mockedApiRequest.mockImplementation((path: string, options?: { signal?: AbortSignal }) => {
    if (/^\/mobile\/trips\/[^/]+\/manifest$/.test(path)) {
      startedManifests += 1;
      return new Promise((_resolve, reject) => {
        options?.signal?.addEventListener('abort', () => {
          reject(Object.assign(new Error('aborted'), { name: 'AbortError' }));
        }, { once: true });
      }) as never;
    }
    return Promise.reject(new Error(`Unexpected API path: ${path}`)) as never;
  });

  const syncing = syncAllTripsWithSummary();
  await waitForCondition(() => startedManifests === 2);
  const replacement = session('passenger');
  replacement.principal.id = '44444444-4444-4444-8444-444444444444';
  useSessionStore.getState().setSession(replacement);

  await expect(syncing).rejects.toMatchObject({ code: 'SYNC_CONTEXT_CHANGED' });
  expect(startedManifests).toBe(2);
});

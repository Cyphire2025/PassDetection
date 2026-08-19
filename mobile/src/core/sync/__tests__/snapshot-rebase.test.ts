import { ApiError } from '@/core/api/api-error';
import { apiRequest } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';

import { resetTripCache } from '../access-cache';
import { captureSyncContext } from '../sync-context';
import { SnapshotContractError } from '../snapshot-rebase-contract';
import {
  beginSnapshotStage,
  discardSnapshotStage,
  promoteSnapshotStage,
  stageSnapshotPage,
} from '../snapshot-rebase-store';
import { performSnapshotRebase, stageCursorPages } from '../snapshot-rebase';

jest.mock('@/core/api/client', () => {
  const actual = jest.requireActual('@/core/api/client');
  return { ...actual, apiRequest: jest.fn() };
});
jest.mock('../access-cache', () => ({ resetTripCache: jest.fn() }));
jest.mock('../snapshot-rebase-store', () => ({
  beginSnapshotStage: jest.fn(),
  discardSnapshotStage: jest.fn(),
  promoteSnapshotStage: jest.fn(),
  stageSnapshotPage: jest.fn(),
}));

const TRIP_ID = '11111111-1111-4111-8111-111111111111';
const AGENCY_ID = '22222222-2222-4222-8222-222222222222';
const PRINCIPAL_ID = '33333333-3333-4333-8333-333333333333';
const PASSENGER_ID = '44444444-4444-4444-8444-444444444444';
const SERVER_TIME = '2030-01-01T00:00:00.000Z';

const mockedApiRequest = jest.mocked(apiRequest);
const mockedReset = jest.mocked(resetTripCache);
const mockedBegin = jest.mocked(beginSnapshotStage);
const mockedDiscard = jest.mocked(discardSnapshotStage);
const mockedPromote = jest.mocked(promoteSnapshotStage);
const mockedStagePage = jest.mocked(stageSnapshotPage);

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

function versions(itinerary = 0, announcements = 0) {
  return {
    manifest: 1,
    itinerary,
    common_documents: 0,
    personal_documents: 0,
    announcements,
    rooming: 0,
    meals: 0,
    qr: 0,
    readiness: 0,
    roster: 0,
  };
}

function descriptor(options: { generation?: number; itinerary?: number; announcements?: number } = {}) {
  const generation = options.generation ?? 3;
  const resourceVersions = versions(options.itinerary, options.announcements);
  const trip = `/api/v1/mobile/trips/${TRIP_ID}`;
  return {
    strategy: 'full_rebase' as const,
    trip: {
      id: TRIP_ID,
      name: 'Enterprise trip',
      destination: null,
      travel_date: null,
      return_date: null,
      role: 'passenger' as const,
      access_generation: generation,
      itinerary_version: resourceVersions.itinerary,
      common_document_version: resourceVersions.common_documents,
      announcement_version: resourceVersions.announcements,
    },
    baseline_cursor: 100_000,
    access_generation: generation,
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

function manifest(value = descriptor()) {
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

function checkpoint() {
  return {
    checkpointCursor: 100_000,
    resourcePath: `/api/v1/mobile/sync/snapshot?trip_id=${TRIP_ID}`,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  useSessionStore.getState().setSession(session());
  mockedBegin.mockResolvedValue(undefined);
  mockedDiscard.mockResolvedValue(undefined);
  mockedPromote.mockResolvedValue(undefined);
  mockedStagePage.mockImplementation(async (_stage, _resource, start, items) => (
    start + items.length
  ));
  mockedReset.mockResolvedValue(undefined);
});

afterEach(() => {
  jest.restoreAllMocks();
  useSessionStore.getState().clear();
});

test('streams a 100,000-item checkpoint resource without a fixed page ceiling', async () => {
  const pageSize = 200;
  const total = 100_000;
  let largestStagedPage = 0;
  let stagedItems = 0;
  const result = await stageCursorPages({
    fetchPage: async (cursor) => {
      const page = cursor ? Number(cursor) : 0;
      const start = page * pageSize;
      return {
        items: Array.from({ length: pageSize }, (_, index) => ({
          id: `item-${start + index}`,
        })),
        next_cursor: start + pageSize < total ? String(page + 1) : null,
        total,
      };
    },
    maximumExpectedItems: total,
    stagePage: async (_start, items) => {
      largestStagedPage = Math.max(largestStagedPage, items.length);
      stagedItems += items.length;
    },
  });

  expect(result).toEqual({ itemCount: 100_000, pageCount: 500 });
  expect(stagedItems).toBe(100_000);
  expect(largestStagedPage).toBe(200);
});

test('successful rebase stages metadata, re-reads S2, and promotes only the stable fence', async () => {
  const stable = descriptor();
  mockedApiRequest.mockImplementation(async (path: string) => {
    if (path.startsWith('/mobile/sync/snapshot?')) return stable as never;
    if (path === `/mobile/trips/${TRIP_ID}/manifest`) return manifest(stable) as never;
    throw new Error(`Unexpected path ${path}`);
  });
  const lease = captureSyncContext();
  try {
    await expect(performSnapshotRebase({
      checkpoint: checkpoint(),
      committedCursor: 50,
      currentAccessGeneration: 3,
      syncContext: lease.context,
      tripId: TRIP_ID,
    })).resolves.toMatchObject({ descriptor: stable, stagedItemCount: 1 });
  } finally {
    lease.release();
  }

  expect(mockedBegin).toHaveBeenCalledTimes(1);
  expect(mockedStagePage).toHaveBeenCalledWith(
    expect.any(Object),
    'manifest',
    0,
    [{ key: 'singleton', payload: manifest(stable) }],
    expect.any(Object),
  );
  expect(mockedPromote).toHaveBeenCalledWith(
    expect.any(Object),
    stable,
    expect.any(Object),
  );
  expect(mockedReset).not.toHaveBeenCalled();
});

test('S1/S2 version race discards staging and retries with jitter before promotion', async () => {
  const first = descriptor();
  const second = descriptor();
  second.versions.manifest = 2;
  let snapshotReads = 0;
  mockedApiRequest.mockImplementation(async (path: string) => {
    if (path.startsWith('/mobile/sync/snapshot?')) {
      snapshotReads += 1;
      return (snapshotReads === 1 ? first : second) as never;
    }
    if (path === `/mobile/trips/${TRIP_ID}/manifest`) {
      return manifest(snapshotReads >= 3 ? second : first) as never;
    }
    throw new Error(`Unexpected path ${path}`);
  });
  const lease = captureSyncContext();
  try {
    await expect(performSnapshotRebase({
      checkpoint: checkpoint(),
      committedCursor: 50,
      currentAccessGeneration: 3,
      syncContext: lease.context,
      tripId: TRIP_ID,
    })).resolves.toMatchObject({ descriptor: second });
  } finally {
    lease.release();
  }

  expect(mockedDiscard).toHaveBeenCalledTimes(1);
  expect(mockedBegin).toHaveBeenCalledTimes(2);
  expect(mockedPromote).toHaveBeenCalledTimes(1);
  expect(mockedPromote).toHaveBeenCalledWith(expect.any(Object), second, expect.any(Object));
});

test('staging failure or kill-before-promotion leaves the live projection unpromoted', async () => {
  const failing = descriptor({ announcements: 1 });
  mockedApiRequest.mockImplementation(async (path: string) => {
    if (path.startsWith('/mobile/sync/snapshot?')) return failing as never;
    if (path === `/mobile/trips/${TRIP_ID}/manifest`) return manifest(failing) as never;
    if (path.startsWith(`/mobile/trips/${TRIP_ID}/announcements?`)) {
      throw new ApiError('invalid page', 400, 'INVALID_RESPONSE', null);
    }
    throw new Error(`Unexpected path ${path}`);
  });
  const lease = captureSyncContext();
  try {
    await expect(performSnapshotRebase({
      checkpoint: checkpoint(),
      committedCursor: 50,
      currentAccessGeneration: 3,
      syncContext: lease.context,
      tripId: TRIP_ID,
    })).rejects.toThrow('invalid page');
  } finally {
    lease.release();
  }

  expect(mockedDiscard).toHaveBeenCalledTimes(1);
  expect(mockedPromote).not.toHaveBeenCalled();
  expect(mockedReset).not.toHaveBeenCalled();
});

test('stale access generation is rejected without purge or promotion', async () => {
  const stale = descriptor({ generation: 2 });
  mockedApiRequest.mockResolvedValue(stale as never);
  const lease = captureSyncContext();
  try {
    await expect(performSnapshotRebase({
      checkpoint: checkpoint(),
      committedCursor: 50,
      currentAccessGeneration: 3,
      syncContext: lease.context,
      tripId: TRIP_ID,
    })).rejects.toThrow('access generation was stale');
  } finally {
    lease.release();
  }

  expect(mockedBegin).not.toHaveBeenCalled();
  expect(mockedReset).not.toHaveBeenCalled();
  expect(mockedPromote).not.toHaveBeenCalled();
});

test('an optional 404 stages an authoritative empty resource and still promotes S2', async () => {
  const optionalMissing = descriptor({ itinerary: 1 });
  mockedApiRequest.mockImplementation(async (path: string) => {
    if (path.startsWith('/mobile/sync/snapshot?')) return optionalMissing as never;
    if (path === `/mobile/trips/${TRIP_ID}/manifest`) return manifest(optionalMissing) as never;
    if (path === `/mobile/trips/${TRIP_ID}/itinerary`) {
      throw new ApiError('not published', 404, 'NOT_FOUND', null);
    }
    throw new Error(`Unexpected path ${path}`);
  });
  const lease = captureSyncContext();
  try {
    await expect(performSnapshotRebase({
      checkpoint: checkpoint(),
      committedCursor: 50,
      currentAccessGeneration: 3,
      syncContext: lease.context,
      tripId: TRIP_ID,
    })).resolves.toMatchObject({ stagedItemCount: 1 });
  } finally {
    lease.release();
  }
  expect(mockedStagePage).toHaveBeenCalledTimes(1);
  expect(mockedPromote).toHaveBeenCalledTimes(1);
});

test.each([
  {
    name: 'singleton itinerary',
    value: descriptor({ itinerary: 1 }),
    route: `/mobile/trips/${TRIP_ID}/itinerary`,
  },
  {
    name: 'paged announcements',
    value: descriptor({ announcements: 1 }),
    route: `/mobile/trips/${TRIP_ID}/announcements?limit=200`,
  },
])('an HTTP_404 for a missing $name route aborts without promotion', async ({ value, route }) => {
  const missingRoute = new ApiError('Not Found', 404, 'HTTP_404', null);
  mockedApiRequest.mockImplementation(async (path: string) => {
    if (path.startsWith('/mobile/sync/snapshot?')) return value as never;
    if (path === `/mobile/trips/${TRIP_ID}/manifest`) return manifest(value) as never;
    if (path === route) throw missingRoute;
    throw new Error(`Unexpected path ${path}`);
  });
  const lease = captureSyncContext();
  try {
    await expect(performSnapshotRebase({
      checkpoint: checkpoint(),
      committedCursor: 50,
      currentAccessGeneration: 3,
      syncContext: lease.context,
      tripId: TRIP_ID,
    })).rejects.toBe(missingRoute);
  } finally {
    lease.release();
  }

  expect(mockedDiscard).toHaveBeenCalledTimes(1);
  expect(mockedPromote).not.toHaveBeenCalled();
});

test('a newer authorization generation is purged before its snapshot can be staged', async () => {
  const advanced = descriptor({ generation: 4 });
  mockedApiRequest.mockImplementation(async (path: string) => {
    if (path.startsWith('/mobile/sync/snapshot?')) return advanced as never;
    if (path === `/mobile/trips/${TRIP_ID}/manifest`) return manifest(advanced) as never;
    throw new Error(`Unexpected path ${path}`);
  });
  const lease = captureSyncContext();
  try {
    await expect(performSnapshotRebase({
      checkpoint: checkpoint(),
      committedCursor: 50,
      currentAccessGeneration: 3,
      syncContext: lease.context,
      tripId: TRIP_ID,
    })).resolves.toMatchObject({ accessGenerationChanged: true });
  } finally {
    lease.release();
  }
  expect(mockedReset).toHaveBeenCalledWith(
    TRIP_ID,
    4,
    advanced.access_expires_at,
    expect.any(Object),
  );
  expect(mockedPromote).toHaveBeenCalledTimes(1);
});

test('repeated resource cursors fail closed even if the page count is otherwise unbounded', async () => {
  await expect(stageCursorPages({
    fetchPage: async () => ({ items: [{ id: 'item' }], next_cursor: 'same' }),
    stagePage: async () => undefined,
  })).rejects.toBeInstanceOf(SnapshotContractError);
});

test('repeated item identifiers across otherwise valid pages fail closed before promotion', async () => {
  const stagePage = jest.fn(async () => undefined);
  let page = 0;
  await expect(stageCursorPages({
    expectedItemCount: 2,
    fetchPage: async () => {
      page += 1;
      return page === 1
        ? { items: [{ id: 'same-item' }], next_cursor: 'next', total: 2 }
        : { items: [{ id: 'same-item' }], next_cursor: null, total: 2 };
    },
    stagePage,
  })).rejects.toThrow('repeated an item identifier');
  expect(stagePage).toHaveBeenCalledTimes(1);
});

test('rejects an over-cap resource before staging the violating page even without a total', async () => {
  const stagePage = jest.fn(async () => undefined);
  let page = 0;
  await expect(stageCursorPages({
    fetchPage: async () => {
      page += 1;
      return page === 1
        ? { items: [{ id: 'first' }, { id: 'second' }], next_cursor: 'next' }
        : { items: [{ id: 'third' }, { id: 'fourth' }], next_cursor: null };
    },
    maximumExpectedItems: 3,
    stagePage,
  })).rejects.toThrow('advertised capacity');
  expect(stagePage).toHaveBeenCalledTimes(1);
  expect(stagePage).toHaveBeenCalledWith(0, [{ id: 'first' }, { id: 'second' }]);
});

test('rejects a final page sequence shorter than the authoritative snapshot count', async () => {
  await expect(stageCursorPages({
    expectedItemCount: 3,
    fetchPage: async () => ({
      items: [{ id: 'first' }, { id: 'second' }],
      next_cursor: null,
    }),
    maximumExpectedItems: 10,
    stagePage: async () => undefined,
  })).rejects.toThrow('snapshot changed');
});

test('rejects a unique cursor that advances without any item progress', async () => {
  const stagePage = jest.fn(async () => undefined);
  await expect(stageCursorPages({
    fetchPage: async () => ({ items: [], next_cursor: 'unique-next-cursor' }),
    maximumExpectedItems: 10,
    stagePage,
  })).rejects.toThrow('did not make progress');
  expect(stagePage).not.toHaveBeenCalled();
});

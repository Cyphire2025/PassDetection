import * as Crypto from 'expo-crypto';

import { ApiError } from '@/core/api/api-error';
import { apiRequest } from '@/core/api/client';
import {
  ManifestSchema,
  SyncSnapshotSchema,
  type SyncSnapshot,
} from '@/core/api/contracts';
import { useSessionStore } from '@/core/auth/session-store';
import {
  AnnouncementListSchema,
  CommonDocumentListSchema,
  DocumentListSchema,
  ItinerarySchema,
  MealSchema,
  PersonalQrSchema,
  ReadinessSchema,
  RoomSchema,
} from '@/features/content/api/content-contracts';
import {
  AttendanceSessionPageSchema,
  CoordinatorRosterSchema,
} from '@/features/coordinator/api/coordinator-contracts';
import {
  ManagerAttendanceSessionPageSchema,
  ManagerRosterSchema,
} from '@/features/manager/api/manager-contracts';

import { resetTripCache } from './access-cache';
import {
  assertSyncContextActive,
  type ImmutableSyncContext,
} from './sync-context';
import {
  assertSameSnapshotFence,
  mobileApiPath,
  SnapshotContractError,
  SnapshotFenceChangedError,
  snapshotVersionsEqual,
  validateSnapshotDescriptor,
  type SnapshotCheckpoint,
  type SnapshotResourceName,
} from './snapshot-rebase-contract';
import {
  beginSnapshotStage,
  discardSnapshotStage,
  promoteSnapshotStage,
  stageSnapshotPage,
  type SnapshotStageIdentity,
} from './snapshot-rebase-store';

const SNAPSHOT_MAX_ATTEMPTS = 3;
const SNAPSHOT_RETRY_BASE_DELAY_MS = 150;

type CursorPage<T> = Readonly<{
  items: readonly T[];
  next_cursor: string | null;
  total?: number;
}>;

export type CursorStageResult = Readonly<{
  itemCount: number;
  pageCount: number;
}>;

export type SnapshotRebaseResult = Readonly<{
  accessGenerationChanged: boolean;
  descriptor: SyncSnapshot;
  stagedItemCount: number;
}>;

export async function stageCursorPages<T extends { id: string }>(options: Readonly<{
  expectedItemCount?: number;
  fetchPage: (cursor: string | null) => Promise<CursorPage<T>>;
  maximumExpectedItems?: number;
  stagePage: (startIndex: number, items: readonly T[]) => Promise<void>;
  validateItems?: (items: readonly T[]) => void;
}>): Promise<CursorStageResult> {
  if (
    options.maximumExpectedItems !== undefined
    && (!Number.isSafeInteger(options.maximumExpectedItems) || options.maximumExpectedItems < 0)
  ) {
    throw new SnapshotContractError('The snapshot resource capacity was invalid.');
  }
  if (
    options.expectedItemCount !== undefined
    && (!Number.isSafeInteger(options.expectedItemCount) || options.expectedItemCount < 0)
  ) {
    throw new SnapshotContractError('The snapshot resource count was invalid.');
  }
  if (
    options.expectedItemCount !== undefined
    && options.maximumExpectedItems !== undefined
    && options.expectedItemCount > options.maximumExpectedItems
  ) {
    throw new SnapshotContractError('The snapshot resource count exceeded its capacity.');
  }
  const seenCursors = new Set<string>();
  const seenItemIds = new Set<string>();
  let cursor: string | null = null;
  let expectedTotal: number | null = null;
  let itemCount = 0;
  let pageCount = 0;

  while (true) {
    const page = await options.fetchPage(cursor);
    options.validateItems?.(page.items);
    for (const item of page.items) {
      if (seenItemIds.has(item.id)) {
        throw new SnapshotContractError('The snapshot resource repeated an item identifier.');
      }
      seenItemIds.add(item.id);
    }
    if (page.total !== undefined) {
      if (!Number.isSafeInteger(page.total) || page.total < 0) {
        throw new SnapshotContractError('The snapshot resource total was invalid.');
      }
      if (
        options.maximumExpectedItems !== undefined
        && page.total > options.maximumExpectedItems
      ) {
        throw new SnapshotContractError('The snapshot resource exceeded its advertised capacity.');
      }
      if (expectedTotal === null) expectedTotal = page.total;
      else if (expectedTotal !== page.total) throw new SnapshotFenceChangedError();
    }

    const nextItemCount = itemCount + page.items.length;
    if (!Number.isSafeInteger(nextItemCount)) {
      throw new SnapshotContractError('The snapshot resource count exceeded a safe integer.');
    }
    if (
      options.maximumExpectedItems !== undefined
      && nextItemCount > options.maximumExpectedItems
    ) {
      throw new SnapshotContractError('The snapshot resource exceeded its advertised capacity.');
    }
    if (expectedTotal !== null && nextItemCount > expectedTotal) {
      throw new SnapshotFenceChangedError();
    }
    if (page.next_cursor !== null) {
      if (page.items.length === 0) {
        throw new SnapshotContractError('The snapshot resource pagination did not make progress.');
      }
      if (
        page.next_cursor.length === 0
        || page.next_cursor === cursor
        || seenCursors.has(page.next_cursor)
      ) {
        throw new SnapshotContractError('The snapshot resource repeated a pagination cursor.');
      }
    }

    await options.stagePage(itemCount, page.items);
    itemCount = nextItemCount;
    pageCount += 1;
    if (page.next_cursor === null) break;
    seenCursors.add(page.next_cursor);
    cursor = page.next_cursor;
  }

  if (expectedTotal !== null && expectedTotal !== itemCount) {
    throw new SnapshotFenceChangedError();
  }
  if (options.expectedItemCount !== undefined && options.expectedItemCount !== itemCount) {
    throw new SnapshotFenceChangedError();
  }
  return { itemCount, pageCount };
}

function waitForRetry(milliseconds: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.reject(signal.reason);
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (operation: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal.removeEventListener('abort', onAbort);
      operation();
    };
    const onAbort = () => finish(() => reject(signal.reason));
    const timer = setTimeout(() => finish(resolve), milliseconds);
    signal.addEventListener('abort', onAbort, { once: true });
    if (signal.aborted) onAbort();
  });
}

export function snapshotRetryDelayMs(attempt: number, random = Math.random): number {
  const ceiling = Math.min(
    2_000,
    SNAPSHOT_RETRY_BASE_DELAY_MS * 2 ** Math.max(0, attempt),
  );
  return Math.floor(random() * ceiling);
}

function retryableSnapshotError(error: unknown): boolean {
  if (error instanceof SnapshotFenceChangedError || error instanceof TypeError) return true;
  return error instanceof ApiError && (
    error.status === 408
    || error.status === 429
    || error.status >= 500
  );
}

function isAuthoritativeSnapshotAbsence(error: unknown): boolean {
  return error instanceof ApiError
    && error.status === 404
    && error.code === 'NOT_FOUND';
}

function activePassengerId(syncContext: ImmutableSyncContext): string {
  assertSyncContextActive(syncContext);
  const principal = useSessionStore.getState().session?.principal;
  if (
    !principal
    || principal.principalType !== 'passenger'
    || !principal.passengerId
  ) {
    throw new SnapshotContractError('The passenger ownership boundary was unavailable.');
  }
  return principal.passengerId;
}

function assertTripItems(
  items: readonly { trip_id: string }[],
  tripId: string,
): void {
  if (items.some((item) => item.trip_id !== tripId)) {
    throw new SnapshotContractError('A snapshot resource crossed its trip boundary.');
  }
}

async function stageSingleton<T extends object>(options: Readonly<{
  fetch: () => Promise<T>;
  resource: SnapshotResourceName;
  stage: SnapshotStageIdentity;
  syncContext: ImmutableSyncContext;
  validate: (value: T) => void;
}>): Promise<number> {
  let value: T;
  try {
    value = await options.fetch();
  } catch (error) {
    if (isAuthoritativeSnapshotAbsence(error)) return 0;
    throw error;
  }
  assertSyncContextActive(options.syncContext);
  options.validate(value);
  await stageSnapshotPage(
    options.stage,
    options.resource,
    0,
    [{ key: 'singleton', payload: value }],
    options.syncContext,
  );
  return 1;
}

async function stagePaged<T extends { id: string }>(options: Readonly<{
  expectedItemCount?: number;
  fetch: (cursor: string | null) => Promise<CursorPage<T>>;
  maximumExpectedItems?: number;
  resource: SnapshotResourceName;
  stage: SnapshotStageIdentity;
  syncContext: ImmutableSyncContext;
  validate: (items: readonly T[]) => void;
}>): Promise<number> {
  let receivedPage = false;
  const result = await stageCursorPages({
    ...(options.expectedItemCount === undefined
      ? {}
      : { expectedItemCount: options.expectedItemCount }),
    fetchPage: async (cursor) => {
      try {
        const page = await options.fetch(cursor);
        receivedPage = true;
        return page;
      } catch (error) {
        if (!receivedPage && cursor === null && isAuthoritativeSnapshotAbsence(error)) {
          return { items: [], next_cursor: null };
        }
        throw error;
      }
    },
    ...(options.maximumExpectedItems === undefined
      ? {}
      : { maximumExpectedItems: options.maximumExpectedItems }),
    stagePage: async (startIndex, items) => {
      await stageSnapshotPage(
        options.stage,
        options.resource,
        startIndex,
        items.map((item) => ({ key: item.id, payload: item })),
        options.syncContext,
      );
    },
    validateItems: options.validate,
  });
  return result.itemCount;
}

function pagedPath(path: string, limit: number, cursor: string | null): string {
  const apiPath = mobileApiPath(path);
  return `${apiPath}${apiPath.includes('?') ? '&' : '?'}limit=${limit}${
    cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''
  }`;
}

function validateManifestFence(manifest: Awaited<ReturnType<typeof fetchManifest>>, descriptor: SyncSnapshot) {
  if (
    manifest.trip.id !== descriptor.trip.id
    || manifest.trip.role !== descriptor.trip.role
    || manifest.trip.access_generation !== descriptor.access_generation
    || !snapshotVersionsEqual(manifest.versions, descriptor.versions)
  ) {
    throw new SnapshotFenceChangedError();
  }
}

function fetchManifest(path: string, syncContext: ImmutableSyncContext) {
  return apiRequest(mobileApiPath(path), {
    schema: ManifestSchema,
    signal: syncContext.signal,
  });
}

async function stageDescriptorResources(
  descriptor: SyncSnapshot,
  stage: SnapshotStageIdentity,
  syncContext: ImmutableSyncContext,
): Promise<number> {
  let itemCount = 0;
  const tripId = stage.tripId;
  const passengerId = descriptor.trip.role === 'passenger'
    ? activePassengerId(syncContext)
    : null;

  const manifest = await fetchManifest(descriptor.resources.manifest, syncContext);
  assertSyncContextActive(syncContext);
  validateManifestFence(manifest, descriptor);
  await stageSnapshotPage(
    stage,
    'manifest',
    0,
    [{ key: 'singleton', payload: manifest }],
    syncContext,
  );
  itemCount += 1;

  if (descriptor.versions.itinerary > 0) {
    itemCount += await stageSingleton({
      fetch: () => apiRequest(mobileApiPath(descriptor.resources.itinerary), {
        schema: ItinerarySchema,
        signal: syncContext.signal,
      }),
      resource: 'itinerary',
      stage,
      syncContext,
      validate: (value) => {
        if (value.trip_id !== tripId || value.version !== descriptor.versions.itinerary) {
          throw new SnapshotFenceChangedError();
        }
      },
    });
  }

  if (descriptor.versions.announcements > 0) {
    itemCount += await stagePaged({
      fetch: (cursor) => apiRequest(
        pagedPath(descriptor.resources.announcements, 200, cursor),
        { schema: AnnouncementListSchema, signal: syncContext.signal },
      ),
      resource: 'announcements',
      expectedItemCount: descriptor.resource_counts.announcements,
      stage,
      syncContext,
      validate: (items) => assertTripItems(items, tripId),
    });
  }

  if (descriptor.versions.common_documents > 0) {
    itemCount += await stagePaged({
      fetch: (cursor) => apiRequest(
        pagedPath(descriptor.resources.common_documents, 200, cursor),
        { schema: CommonDocumentListSchema, signal: syncContext.signal },
      ),
      resource: 'common_documents',
      expectedItemCount: descriptor.resource_counts.common_documents,
      stage,
      syncContext,
      validate: (items) => assertTripItems(items, tripId),
    });
  }

  if (
    descriptor.trip.role === 'passenger'
    && descriptor.resources.personal_documents
    && descriptor.versions.personal_documents > 0
  ) {
    itemCount += await stagePaged({
      fetch: (cursor) => apiRequest(
        pagedPath(descriptor.resources.personal_documents!, 200, cursor),
        { schema: DocumentListSchema, signal: syncContext.signal },
      ),
      resource: 'personal_documents',
      expectedItemCount: descriptor.resource_counts.personal_documents!,
      stage,
      syncContext,
      validate: (items) => {
        assertTripItems(items, tripId);
        if (items.some((item) => (
          item.scope !== 'personal' || item.passenger_id !== passengerId
        ))) {
          throw new SnapshotContractError('A personal document crossed its passenger boundary.');
        }
      },
    });
  }

  if (descriptor.trip.role === 'passenger') {
    if (descriptor.resources.room && descriptor.versions.rooming > 0) {
      itemCount += await stageSingleton({
        fetch: () => apiRequest(mobileApiPath(descriptor.resources.room!), {
          schema: RoomSchema,
          signal: syncContext.signal,
        }),
        resource: 'room',
        stage,
        syncContext,
        validate: (value) => {
          if (
            value.trip_id !== tripId
            || value.passenger_id !== passengerId
            || value.version !== descriptor.versions.rooming
          ) throw new SnapshotFenceChangedError();
        },
      });
    }
    if (descriptor.resources.meals && descriptor.versions.meals > 0) {
      itemCount += await stageSingleton({
        fetch: () => apiRequest(mobileApiPath(descriptor.resources.meals!), {
          schema: MealSchema,
          signal: syncContext.signal,
        }),
        resource: 'meals',
        stage,
        syncContext,
        validate: (value) => {
          if (
            value.trip_id !== tripId
            || value.passenger_id !== passengerId
            || value.version !== descriptor.versions.meals
          ) throw new SnapshotFenceChangedError();
        },
      });
    }
    if (descriptor.resources.qr && descriptor.versions.qr > 0) {
      itemCount += await stageSingleton({
        fetch: () => apiRequest(mobileApiPath(descriptor.resources.qr!), {
          schema: PersonalQrSchema,
          signal: syncContext.signal,
        }),
        resource: 'qr',
        stage,
        syncContext,
        validate: (value) => {
          if (
            value.trip_id !== tripId
            || value.passenger_id !== passengerId
            || value.version !== descriptor.versions.qr
          ) throw new SnapshotFenceChangedError();
        },
      });
    }
  }

  if (
    descriptor.trip.role === 'client_manager'
    && descriptor.resources.readiness
    && descriptor.versions.readiness > 0
  ) {
    itemCount += await stageSingleton({
      fetch: () => apiRequest(mobileApiPath(descriptor.resources.readiness!), {
        schema: ReadinessSchema,
        signal: syncContext.signal,
      }),
      resource: 'readiness',
      stage,
      syncContext,
      validate: (value) => {
        if (
          value.trip_id !== tripId
          || value.version !== descriptor.versions.readiness
        ) throw new SnapshotFenceChangedError();
      },
    });
  }

  if (
    descriptor.resources.roster
    && descriptor.versions.roster > 0
    && descriptor.trip.role === 'coordinator'
  ) {
    itemCount += await stagePaged({
      fetch: async (cursor) => {
        const page = await apiRequest(
          pagedPath(descriptor.resources.roster!, 200, cursor),
          { schema: CoordinatorRosterSchema, signal: syncContext.signal },
        );
        if (page.roster_revision !== descriptor.versions.roster) {
          throw new SnapshotFenceChangedError();
        }
        return page;
      },
      maximumExpectedItems: descriptor.max_group_passengers,
      expectedItemCount: descriptor.resource_counts.roster!,
      resource: 'roster',
      stage,
      syncContext,
      validate: () => undefined,
    });
  } else if (
    descriptor.resources.roster
    && descriptor.versions.roster > 0
    && descriptor.trip.role === 'client_manager'
  ) {
    itemCount += await stagePaged({
      fetch: (cursor) => apiRequest(
        pagedPath(descriptor.resources.roster!, 200, cursor),
        { schema: ManagerRosterSchema, signal: syncContext.signal },
      ),
      maximumExpectedItems: descriptor.max_group_passengers,
      expectedItemCount: descriptor.resource_counts.roster!,
      resource: 'roster',
      stage,
      syncContext,
      validate: () => undefined,
    });
  }

  if (descriptor.resources.attendance_sessions && descriptor.trip.role === 'coordinator') {
    itemCount += await stagePaged({
      fetch: (cursor) => apiRequest(
        pagedPath(descriptor.resources.attendance_sessions!, 100, cursor),
        { schema: AttendanceSessionPageSchema, signal: syncContext.signal },
      ),
      resource: 'attendance_sessions',
      expectedItemCount: descriptor.resource_counts.attendance_sessions!,
      maximumExpectedItems: descriptor.max_attendance_sessions_per_group,
      stage,
      syncContext,
      validate: () => undefined,
    });
  } else if (
    descriptor.resources.attendance_sessions
    && descriptor.trip.role === 'client_manager'
  ) {
    itemCount += await stagePaged({
      fetch: (cursor) => apiRequest(
        pagedPath(descriptor.resources.attendance_sessions!, 100, cursor),
        { schema: ManagerAttendanceSessionPageSchema, signal: syncContext.signal },
      ),
      resource: 'attendance_sessions',
      expectedItemCount: descriptor.resource_counts.attendance_sessions!,
      maximumExpectedItems: descriptor.max_attendance_sessions_per_group,
      stage,
      syncContext,
      validate: () => undefined,
    });
  }

  return itemCount;
}

export async function performSnapshotRebase(options: Readonly<{
  checkpoint: SnapshotCheckpoint;
  committedCursor: number;
  currentAccessGeneration: number;
  syncContext: ImmutableSyncContext;
  tripId: string;
}>): Promise<SnapshotRebaseResult> {
  let accessGeneration = options.currentAccessGeneration;
  let committedCursor = options.committedCursor;
  let accessGenerationChanged = false;
  let lastError: unknown = null;

  for (let attempt = 0; attempt < SNAPSHOT_MAX_ATTEMPTS; attempt += 1) {
    assertSyncContextActive(options.syncContext);
    let stage: SnapshotStageIdentity | null = null;
    try {
      const first = await apiRequest(mobileApiPath(options.checkpoint.resourcePath), {
        schema: SyncSnapshotSchema,
        signal: options.syncContext.signal,
      });
      assertSyncContextActive(options.syncContext);
      validateSnapshotDescriptor(first, {
        checkpointCursor: options.checkpoint.checkpointCursor,
        committedCursor,
        currentAccessGeneration: accessGeneration,
        role: options.syncContext.role,
        tripId: options.tripId,
      });

      if (first.access_generation > accessGeneration) {
        await resetTripCache(
          options.tripId,
          first.access_generation,
          first.access_expires_at,
          options.syncContext,
        );
        accessGeneration = first.access_generation;
        committedCursor = 0;
        accessGenerationChanged = true;
      }

      stage = {
        generationId: Crypto.randomUUID(),
        namespace: options.syncContext.namespace,
        tripId: options.tripId,
      };
      await beginSnapshotStage(stage, options.syncContext);
      const stagedItemCount = await stageDescriptorResources(
        first,
        stage,
        options.syncContext,
      );
      const second = await apiRequest(mobileApiPath(options.checkpoint.resourcePath), {
        schema: SyncSnapshotSchema,
        signal: options.syncContext.signal,
      });
      assertSyncContextActive(options.syncContext);
      validateSnapshotDescriptor(second, {
        checkpointCursor: options.checkpoint.checkpointCursor,
        committedCursor,
        currentAccessGeneration: accessGeneration,
        role: options.syncContext.role,
        tripId: options.tripId,
      });
      if (second.access_generation > first.access_generation) {
        await resetTripCache(
          options.tripId,
          second.access_generation,
          second.access_expires_at,
          options.syncContext,
        );
        accessGeneration = second.access_generation;
        committedCursor = 0;
        accessGenerationChanged = true;
      }
      assertSameSnapshotFence(first, second);
      await promoteSnapshotStage(stage, second, options.syncContext);
      return { accessGenerationChanged, descriptor: second, stagedItemCount };
    } catch (error) {
      lastError = error;
      if (stage) {
        await discardSnapshotStage(stage, options.syncContext).catch(() => undefined);
      }
      if (!retryableSnapshotError(error) || attempt + 1 >= SNAPSHOT_MAX_ATTEMPTS) throw error;
      await waitForRetry(snapshotRetryDelayMs(attempt), options.syncContext.signal);
    }
  }
  throw lastError;
}

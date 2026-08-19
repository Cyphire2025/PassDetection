import { ApiError, apiRequest } from '@/core/api/client';
import {
  ManifestSchema,
  type MobileResourceVersions,
  SyncAckResponseSchema,
  SyncPageSchema,
  type SyncChangeSchema,
} from '@/core/api/contracts';
import type { MobileRole } from '@/core/auth/types';
import { AbortableSharedTaskRegistry } from '@/core/async/abortable-shared-task';
import {
  recordMobileMetric,
  type MobileMetricAttributes,
} from '@/core/observability/mobile-observability';
import { recordTripDurableQueueDepths } from '@/core/observability/queue-depth-observability';
import { mobileQueryClient } from '@/core/query/query-client';
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
  type OfflinePrefetchProgress,
} from '@/features/content/data/content-repository';
import { refreshItinerary } from '@/features/content/data/itinerary-repository';
import {
  applyCoordinatorPassengerChanges,
  loadAttendanceSummary,
  syncFullRoster,
} from '@/features/coordinator/data/coordinator-repository';
import { drainAttendanceQueue } from '@/features/coordinator/data/attendance-queue';
import { drainIncidentQueue } from '@/features/coordinator/data/operations-repository';
import { drainNotificationReads } from '@/features/notifications/data/notification-repository';
import {
  localTripsInContext,
  refreshTripsInContext,
} from '@/features/trips/data/trip-repository';
import type { Trip } from '@/features/trips/model/trip';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';
import type { z } from 'zod';

import { ensureTripPurgeCompleted, purgeTripCache, resetTripCache } from './access-cache';
import {
  assertCursorAdvance,
  classifySyncFailure,
  hasActualSyncChanges,
  requiresBaselineSync,
  resourceVersionChanges,
  safeSyncFailureCode,
  type SyncFailureCategory,
} from './sync-policy';
import { queryKeyMatchesChangedProjection, tripCollectionsDiffer } from './sync-runtime-policy';
import {
  assertSyncContextActive,
  captureSyncContext,
  isSyncContextChanged,
  SyncContextChangedError,
  type ImmutableSyncContext,
} from './sync-context';
import {
  mobileApiPath,
  snapshotCheckpointFromPage,
} from './snapshot-rebase-contract';
import { performSnapshotRebase } from './snapshot-rebase';

const MAX_SYNC_PAGES = 20;
const SYNC_PAGE_SIZE = 500;
const FULL_SYNC_CONCURRENCY = 2;
const tripSyncTasks = new AbortableSharedTaskRegistry<string, SyncResult>();
const fullSyncTasks = new AbortableSharedTaskRegistry<string, SyncAllTripsSummary>();
const documentHydrationInFlight = new Map<string, Promise<OfflinePrefetchProgress>>();

type SyncChange = z.infer<typeof SyncChangeSchema>;

async function acknowledgeCommittedSync(options: Readonly<{
  accessGeneration: number;
  cursor: number;
  path: string;
  syncContext: ImmutableSyncContext;
  tripId: string;
  versions: MobileResourceVersions;
}>): Promise<void> {
  const acknowledgement = await apiRequest(options.path, {
    method: 'POST',
    body: {
      trip_id: options.tripId,
      cursor: options.cursor,
      access_generation: options.accessGeneration,
      versions: options.versions,
    },
    schema: SyncAckResponseSchema,
    signal: options.syncContext.signal,
  });
  assertSyncContextActive(options.syncContext);
  if (
    acknowledgement.trip_id !== options.tripId
    || acknowledgement.cursor !== options.cursor
    || acknowledgement.access_generation !== options.accessGeneration
  ) {
    throw new Error('The synchronization acknowledgement was out of scope.');
  }
}

async function drainDurableSyncQueues(
  tripId: string,
  role: MobileRole,
  syncContext: ImmutableSyncContext,
): Promise<void> {
  const durableQueues: Promise<unknown>[] = [drainNotificationReads(tripId, syncContext)];
  if (role === 'coordinator') {
    durableQueues.push(drainAttendanceQueue(tripId), drainIncidentQueue(tripId));
  }
  await Promise.all(durableQueues.map((request) => request.catch(() => undefined)));
  assertSyncContextActive(syncContext);
  const database = await openAccountDatabase(syncContext.namespace);
  assertSyncContextActive(syncContext);
  await recordTripDurableQueueDepths(database, syncContext.namespace, tripId);
  assertSyncContextActive(syncContext);
}
export type SyncResult = {
  tripId: string;
  cursor: number;
  changes: number;
  changed: boolean;
  syncedAt: string;
  documentPrefetch: OfflinePrefetchProgress | null;
};

export type SyncTripOptions = {
  documentHydration?: 'wait' | 'background';
  onDocumentProgress?: (progress: OfflinePrefetchProgress) => void;
  signal?: AbortSignal;
};

export type SyncAllTripsSummary = {
  results: SyncResult[];
  failures: SyncTripFailure[];
  requestedTripCount: number;
  tripsChanged: boolean;
  removedTripIds: string[];
};

export type SyncAllTripsOptions = Readonly<{
  signal?: AbortSignal;
}>;

export type SyncTripFailure = Readonly<{
  tripId: string;
  category: SyncFailureCategory;
  retryable: boolean;
  code: string;
}>;

export function syncTripFailure(tripId: string, error: unknown): SyncTripFailure {
  const failure = classifySyncFailure(error);
  return { tripId, ...failure };
}

function sameSyncIdentity(
  left: ImmutableSyncContext,
  right: ImmutableSyncContext,
): boolean {
  return (
    left.sessionId === right.sessionId &&
    left.namespace === right.namespace &&
    left.agencyId === right.agencyId &&
    left.principalId === right.principalId &&
    left.role === right.role
  );
}

function hydrateDocuments(
  tripId: string,
  syncContext: ImmutableSyncContext,
  onProgress?: (progress: OfflinePrefetchProgress) => void,
): Promise<OfflinePrefetchProgress> {
  return syncContext.role === 'passenger'
    ? prefetchPassengerOfflineDocuments(tripId, onProgress, syncContext)
    : prefetchCommonOfflineDocuments(tripId, onProgress, syncContext);
}

function scheduleDocumentHydration(
  tripId: string,
  parentContext: ImmutableSyncContext,
): Promise<OfflinePrefetchProgress> {
  assertSyncContextActive(parentContext);
  const lease = captureSyncContext();
  if (!sameSyncIdentity(parentContext, lease.context)) {
    lease.release();
    assertSyncContextActive(parentContext);
    throw new Error('The document hydration account context changed unexpectedly.');
  }

  const key = [
    lease.context.namespace,
    lease.context.sessionId,
    lease.context.principalId,
    tripId,
  ].join(':');
  const active = documentHydrationInFlight.get(key);
  if (active) {
    lease.release();
    return active;
  }

  const request = hydrateDocuments(tripId, lease.context).finally(() => {
    if (documentHydrationInFlight.get(key) === request) {
      documentHydrationInFlight.delete(key);
    }
    lease.release();
  });
  documentHydrationInFlight.set(key, request);
  return request;
}

function runBackgroundDocumentHydration(
  tripId: string,
  syncContext: ImmutableSyncContext,
): void {
  let request: Promise<OfflinePrefetchProgress>;
  try {
    request = scheduleDocumentHydration(tripId, syncContext);
  } catch {
    return;
  }
  void request
    .catch(() => undefined)
    .finally(() => {
      try {
        assertSyncContextActive(syncContext);
        void mobileQueryClient.invalidateQueries({
          predicate: (query) => query.queryKey.includes(syncContext.namespace)
            && queryKeyMatchesChangedProjection(query.queryKey, [tripId]),
          refetchType: 'active',
        });
      } catch {
        // Publication is best effort. The durable document job remains the
        // source of truth and the next reconciliation will publish it again.
      }
    });
}

/**
 * Starts the existing account-scoped, deduplicated document hydration lane
 * without keeping a cached workspace behind the preparation screen. The
 * captured lease is retained by scheduleDocumentHydration and is cancelled by
 * the normal authentication boundary if the active account changes.
 */
export function scheduleTripDocumentHydration(tripId: string): void {
  let lease: ReturnType<typeof captureSyncContext> | null = null;
  try {
    lease = captureSyncContext();
    runBackgroundDocumentHydration(tripId, lease.context);
  } catch {
    // A durable offline-document job remains authoritative. The sync runtime
    // will retry it after the next active/online trigger.
  } finally {
    lease?.release();
  }
}

function resourcePath(value: string): string {
  const prefix = '/api/v1';
  if (!value.startsWith(`${prefix}/mobile/`) || value.includes('://')) {
    throw new Error('The manifest contained an invalid mobile resource path.');
  }
  return value.slice(prefix.length);
}

async function localTripState(tripId: string, syncContext: ImmutableSyncContext) {
  assertSyncContextActive(syncContext);
  const { namespace } = syncContext;
  const database = await openAccountDatabase(namespace);
  assertSyncContextActive(syncContext);
  const trip = await database.getFirstAsync<{
    access_generation: number;
    itinerary_version: number;
    common_document_version: number;
    personal_document_version: number;
    announcement_version: number;
    readiness_version: number;
    roster_version: number;
    rooming_version: number;
    meals_version: number;
    qr_version: number;
  }>(`SELECT access_generation, itinerary_version, common_document_version,
             personal_document_version, announcement_version, readiness_version, roster_version,
             rooming_version, meals_version, qr_version
        FROM trips WHERE account_namespace = ? AND id = ?`, namespace, tripId);
  const cursor = await database.getFirstAsync<{ cursor: number }>(
    'SELECT cursor FROM sync_cursors WHERE account_namespace = ? AND trip_id = ?',
    namespace,
    tripId,
  );
  assertSyncContextActive(syncContext);
  return { trip, cursor: cursor?.cursor ?? 0, hasCursor: Boolean(cursor) };
}

async function storeManifest(
  tripId: string,
  manifest: z.infer<typeof ManifestSchema>,
  syncContext: ImmutableSyncContext,
): Promise<void> {
  assertSyncContextActive(syncContext);
  const { namespace, agencyId } = syncContext;
  const database = await openAccountDatabase(namespace);
  assertSyncContextActive(syncContext);
  await database.runAsync(
    `INSERT INTO trips
      (id, account_namespace, agency_id, role, name, destination, travel_date, return_date, timezone,
       access_generation, access_expires_at,
       itinerary_version, common_document_version, personal_document_version,
       announcement_version, readiness_version, roster_version, rooming_version,
       meals_version, qr_version,
       advertised_itinerary_version, advertised_common_document_version,
       advertised_personal_document_version, advertised_announcement_version,
       advertised_readiness_version, advertised_roster_version,
       advertised_rooming_version, advertised_meals_version, advertised_qr_version,
       updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, -1, -1, -1, -1, -1, -1, -1, -1, -1,
       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(id) DO UPDATE SET
       role = excluded.role, name = excluded.name, destination = excluded.destination,
       travel_date = excluded.travel_date, return_date = excluded.return_date,
       timezone = excluded.timezone,
       access_generation = excluded.access_generation, access_expires_at = excluded.access_expires_at,
       advertised_itinerary_version = excluded.advertised_itinerary_version,
       advertised_common_document_version = excluded.advertised_common_document_version,
       advertised_personal_document_version = excluded.advertised_personal_document_version,
       advertised_announcement_version = excluded.advertised_announcement_version,
       advertised_readiness_version = excluded.advertised_readiness_version,
       advertised_roster_version = excluded.advertised_roster_version,
       advertised_rooming_version = excluded.advertised_rooming_version,
       advertised_meals_version = excluded.advertised_meals_version,
       advertised_qr_version = excluded.advertised_qr_version,
       updated_at = excluded.updated_at`,
    tripId,
    namespace,
    agencyId,
    manifest.trip.role,
    manifest.trip.name,
    manifest.trip.destination,
    manifest.trip.travel_date,
    manifest.trip.return_date,
    manifest.trip.timezone,
    manifest.trip.access_generation,
    manifest.access_expires_at,
    manifest.versions.itinerary,
    manifest.versions.common_documents,
    manifest.versions.personal_documents,
    manifest.versions.announcements,
    manifest.versions.readiness,
    manifest.versions.roster,
    manifest.versions.rooming,
    manifest.versions.meals,
    manifest.versions.qr,
    manifest.server_time,
  );
}

async function finalizeSyncState(
  tripId: string,
  cursor: number,
  accessGeneration: number,
  syncedAt: string,
  versions: z.infer<typeof ManifestSchema>['versions'],
  syncContext: ImmutableSyncContext,
): Promise<void> {
  assertSyncContextActive(syncContext);
  const { namespace } = syncContext;
  const database = await openAccountDatabase(namespace);
  assertSyncContextActive(syncContext);
  await withAccountTransaction(database, async (transaction) => {
    assertSyncContextActive(syncContext);
    const applied = await transaction.runAsync(
      `UPDATE trips SET
         itinerary_version = ?, common_document_version = ?, personal_document_version = ?,
         announcement_version = ?, readiness_version = ?, roster_version = ?,
         rooming_version = ?, meals_version = ?, qr_version = ?
       WHERE account_namespace = ? AND id = ? AND access_generation = ?
         AND advertised_itinerary_version = ?
         AND advertised_common_document_version = ?
         AND advertised_personal_document_version = ?
         AND advertised_announcement_version = ?
         AND advertised_readiness_version = ?
         AND advertised_roster_version = ?
         AND advertised_rooming_version = ?
         AND advertised_meals_version = ?
         AND advertised_qr_version = ?`,
      versions.itinerary,
      versions.common_documents,
      versions.personal_documents,
      versions.announcements,
      versions.readiness,
      versions.roster,
      versions.rooming,
      versions.meals,
      versions.qr,
      namespace,
      tripId,
      accessGeneration,
      versions.itinerary,
      versions.common_documents,
      versions.personal_documents,
      versions.announcements,
      versions.readiness,
      versions.roster,
      versions.rooming,
      versions.meals,
      versions.qr,
    );
    if (applied.changes !== 1) {
      throw new Error('The trip manifest changed before synchronization could be finalized.');
    }
    assertSyncContextActive(syncContext);
    await transaction.runAsync(
      `INSERT INTO sync_cursors
        (account_namespace, trip_id, cursor, access_generation, last_synced_at, last_error_code)
       VALUES (?, ?, ?, ?, ?, NULL)
       ON CONFLICT(account_namespace, trip_id) DO UPDATE SET
         cursor = excluded.cursor, access_generation = excluded.access_generation,
         last_synced_at = excluded.last_synced_at, last_error_code = NULL`,
      namespace,
      tripId,
      cursor,
      accessGeneration,
      syncedAt,
    );
  });
}

async function storeSyncFailure(
  tripId: string,
  error: unknown,
  syncContext: ImmutableSyncContext,
): Promise<void> {
  assertSyncContextActive(syncContext);
  const database = await openAccountDatabase(syncContext.namespace);
  assertSyncContextActive(syncContext);
  await database.runAsync(
    `INSERT INTO sync_cursors
       (account_namespace, trip_id, cursor, access_generation, last_synced_at, last_error_code)
     VALUES (?, ?, 0, 0, NULL, ?)
     ON CONFLICT(account_namespace, trip_id) DO UPDATE SET
       last_error_code = excluded.last_error_code`,
    syncContext.namespace,
    tripId,
    safeSyncFailureCode(error),
  );
}

function changeFlags(changes: SyncChange[]) {
  const types = new Set(changes.map((change) => change.entity_type));
  const passengerChanges = changes.flatMap((change) =>
    change.entity_type === 'coordinator_passenger' &&
    change.entity_id &&
    (change.operation === 'upsert' || change.operation === 'delete')
      ? [{ passengerId: change.entity_id, operation: change.operation }]
      : [],
  );
  return {
    revoke: changes.some((change) => {
      if (change.operation === 'revoke') return true;
      if (!['group_access', 'gc_group_access', 'role_access'].includes(change.entity_type)) return false;
      const payload = change.payload;
      return typeof payload === 'object' && payload !== null && 'enabled' in payload && payload.enabled === false;
    }),
    itinerary: [...types].some((value) => value.includes('itinerary')),
    announcements: types.has('announcement'),
    documents: [...types].some((value) => value.includes('document')),
    room: [...types].some((value) => value.includes('room')),
    meals: [...types].some((value) => value.includes('meal')),
    qr: [...types].some((value) => value.includes('qr')),
    readiness: [...types].some((value) => value.includes('readiness') || value.includes('passport') || value.includes('visa') || value.includes('ticket')),
    roster: changes.some(
      (change) =>
        change.entity_type !== 'coordinator_passenger' &&
        (change.entity_type.includes('passenger') || change.entity_type.includes('attendance')),
    ),
    attendance: [...types].some(
      (value) => value.includes('attendance') || value === 'coordinator_passenger',
    ),
    passengerChanges,
  };
}

function coordinatorPassengerDeltaCoversRevision(
  changes: SyncChange[],
  authoritativeRosterRevision: number,
): boolean {
  const targeted = changes.filter(
    (change) =>
      change.entity_type === 'coordinator_passenger' &&
      Boolean(change.entity_id) &&
      (change.operation === 'upsert' || change.operation === 'delete'),
  );
  const latest = targeted.at(-1);
  if (!latest || typeof latest.payload !== 'object' || latest.payload === null) return false;
  const revision = Reflect.get(latest.payload, 'roster_revision');
  return (
    typeof revision === 'number' &&
    Number.isSafeInteger(revision) &&
    revision >= 0 &&
    revision === authoritativeRosterRevision
  );
}

async function refreshChangedResources(
  tripId: string,
  role: MobileRole,
  flags: ReturnType<typeof changeFlags>,
  baseline: boolean,
  versions: z.infer<typeof ManifestSchema>['versions'],
  resources: z.infer<typeof ManifestSchema>['resources'],
  syncContext: ImmutableSyncContext,
): Promise<void> {
  assertSyncContextActive(syncContext);
  const requests: Promise<unknown>[] = [];
  // Every scheduled projection is required to finish authoritatively before
  // versions and cursor advance. Resource handlers may normalize only explicit
  // domain absence after clearing stale local rows (for example unpublished
  // itinerary or unavailable personal QR). Route-level HTTP_404 and cached
  // offline fallbacks are failures at this synchronization boundary.
  if ((baseline && versions.itinerary > 0) || flags.itinerary) {
    requests.push(refreshItinerary(tripId, syncContext, resourcePath(resources.itinerary)));
  }
  if ((baseline && versions.announcements > 0) || flags.announcements) {
    requests.push(refreshAnnouncements(tripId, syncContext, resourcePath(resources.announcements)));
  }
  if ((baseline && versions.common_documents > 0) || flags.documents) {
    requests.push(refreshCommonDocuments(
      tripId,
      syncContext,
      resourcePath(resources.common_documents),
    ));
  }
  if (role === 'passenger') {
    if (baseline || flags.documents) {
      requests.push(refreshDocuments(
        tripId,
        syncContext,
        resourcePath(resources.personal_documents),
      ));
    }
    if ((baseline && versions.rooming > 0) || flags.room) {
      requests.push(loadRoom(tripId, syncContext, resourcePath(resources.room)));
    }
    if ((baseline && versions.meals > 0) || flags.meals) {
      requests.push(loadMeal(tripId, syncContext, resourcePath(resources.meals)));
    }
    if ((baseline && versions.qr > 0) || flags.qr) {
      requests.push(refreshQr(tripId, syncContext, resourcePath(resources.qr)));
    }
  } else if (role === 'client_manager') {
    if (baseline || flags.readiness) requests.push(loadReadiness(tripId, syncContext));
  } else {
    if (baseline || flags.roster || flags.room || flags.meals) {
      requests.push(syncFullRoster(tripId, syncContext, versions.roster));
    }
    else if (flags.passengerChanges.length) {
      requests.push(applyCoordinatorPassengerChanges(tripId, flags.passengerChanges, syncContext));
    }
    if (baseline || flags.roster || flags.attendance) {
      requests.push(loadAttendanceSummary(tripId, syncContext));
    }
  }
  await Promise.all(requests);
  assertSyncContextActive(syncContext);
}

async function performTripSync(
  tripId: string,
  syncContext: ImmutableSyncContext,
): Promise<SyncResult> {
  assertSyncContextActive(syncContext);
  const { role } = syncContext;
  try {
    // A durable purge tombstone blocks every old-generation restore until the
    // corresponding encrypted vault directory has actually been removed.
    await ensureTripPurgeCompleted(tripId, syncContext);
    assertSyncContextActive(syncContext);
    const previous = await localTripState(tripId, syncContext);
    const manifest = await apiRequest(`/mobile/trips/${tripId}/manifest`, {
      schema: ManifestSchema,
      signal: syncContext.signal,
    });
    assertSyncContextActive(syncContext);
    if (manifest.trip.id !== tripId || manifest.trip.role !== role) {
      await purgeTripCache(tripId, syncContext);
      throw new Error('The manifest identity did not match this workspace.');
    }
    const serverNow = Date.parse(manifest.server_time);
    const expiresAt = manifest.access_expires_at ? Date.parse(manifest.access_expires_at) : null;
    if (!Number.isFinite(serverNow) || (expiresAt !== null && (!Number.isFinite(expiresAt) || expiresAt <= serverNow))) {
      await purgeTripCache(tripId, syncContext);
      throw new Error('Trip access has expired.');
    }
    if (previous.trip && previous.trip.access_generation !== manifest.trip.access_generation) {
      await resetTripCache(
        tripId,
        manifest.trip.access_generation,
        manifest.access_expires_at,
        syncContext,
      );
      previous.cursor = 0;
      previous.hasCursor = false;
    }
    await storeManifest(tripId, manifest, syncContext);

    const cursorAheadOfServer = previous.cursor > manifest.sync_cursor;
    let cursor = cursorAheadOfServer ? 0 : previous.cursor;
    let pages = 0;
    let changeCount = 0;
    const baseline = requiresBaselineSync({
      hasTrip: Boolean(previous.trip),
      hasCursor: previous.hasCursor,
      cursorAheadOfServer,
    });
    const aggregate: SyncChange[] = [];
    const syncPath = resourcePath(manifest.resources.sync_changes);
    while (true) {
      assertSyncContextActive(syncContext);
      if (pages >= MAX_SYNC_PAGES) throw new Error('Synchronization exceeded its bounded page limit.');
      const query = new URLSearchParams({ trip_id: tripId, cursor: String(cursor), limit: String(SYNC_PAGE_SIZE) });
      const separator = syncPath.includes('?') ? '&' : '?';
      const page = await apiRequest(`${syncPath}${separator}${query.toString()}`, {
        schema: SyncPageSchema,
        signal: syncContext.signal,
      });
      assertSyncContextActive(syncContext);
      assertCursorAdvance(cursor, page.next_cursor, page.has_more);
      let sequence = cursor;
      for (const change of page.changes) {
        if (change.group_id !== tripId || change.sequence <= sequence) throw new Error('Synchronization changes were out of scope or order.');
        sequence = change.sequence;
      }
      const checkpoint = snapshotCheckpointFromPage(page, tripId);
      if (checkpoint) {
        // A checkpoint is a control fence, never an ordinary resource flag.
        // Stage every authorized metadata projection and publish it in one
        // SQLite transaction before any document bytes are considered.
        const rebased = await performSnapshotRebase({
          checkpoint,
          committedCursor: previous.cursor,
          currentAccessGeneration: manifest.trip.access_generation,
          syncContext,
          tripId,
        });
        const committed = rebased.descriptor;
        try {
          await acknowledgeCommittedSync({
            accessGeneration: committed.access_generation,
            cursor: committed.baseline_cursor,
            path: mobileApiPath(committed.resources.acknowledge),
            syncContext,
            tripId,
            versions: committed.versions,
          });
        } catch (error) {
          if (isSyncContextChanged(error)) assertSyncContextActive(syncContext);
          // The local generation is already durable. A 409/version race is
          // reconciled by the immediate next delta pass from this exact cursor.
        }
        await drainDurableSyncQueues(tripId, role, syncContext);
        return {
          tripId,
          cursor: committed.baseline_cursor,
          changes: changeCount + 1,
          changed: true,
          syncedAt: committed.server_time,
          documentPrefetch: null,
        };
      }
      aggregate.push(...page.changes);
      const flags = changeFlags(page.changes);
      if (flags.revoke) {
        await purgeTripCache(tripId, syncContext);
        throw new Error('Trip access was revoked.');
      }
      cursor = page.next_cursor;
      pages += 1;
      changeCount += page.changes.length;
      if (!page.has_more) break;
    }

    const versionChanged = resourceVersionChanges(
      previous.trip ? {
        itinerary: previous.trip.itinerary_version,
        commonDocuments: previous.trip.common_document_version,
        personalDocuments: previous.trip.personal_document_version,
        announcements: previous.trip.announcement_version,
        readiness: previous.trip.readiness_version,
        roster: previous.trip.roster_version,
        rooming: previous.trip.rooming_version,
        meals: previous.trip.meals_version,
        qr: previous.trip.qr_version,
      } : null,
      {
        itinerary: manifest.versions.itinerary,
        commonDocuments: manifest.versions.common_documents,
        personalDocuments: manifest.versions.personal_documents,
        announcements: manifest.versions.announcements,
        readiness: manifest.versions.readiness,
        roster: manifest.versions.roster,
        rooming: manifest.versions.rooming,
        meals: manifest.versions.meals,
        qr: manifest.versions.qr,
      },
    );
    const flags = changeFlags(aggregate);
    const targetedRosterDeltaIsComplete =
      role === 'coordinator' &&
      coordinatorPassengerDeltaCoversRevision(aggregate, manifest.versions.roster);
    const effectiveFlags = {
      ...flags,
      itinerary: flags.itinerary || versionChanged.itinerary,
      documents: flags.documents || versionChanged.commonDocuments || versionChanged.personalDocuments,
      announcements: flags.announcements || versionChanged.announcements,
      readiness: flags.readiness || versionChanged.readiness,
      // A coordinator passenger event is safe to apply without downloading the
      // complete roster only when its event-time authoritative proof equals
      // the manifest. Missing/stale proofs fail closed to the full sync.
      roster:
        flags.roster ||
        (versionChanged.roster && !targetedRosterDeltaIsComplete),
      room: flags.room || versionChanged.rooming,
      meals: flags.meals || versionChanged.meals,
      qr: flags.qr || versionChanged.qr,
    };
    await refreshChangedResources(
      tripId,
      role,
      effectiveFlags,
      baseline,
      manifest.versions,
      manifest.resources,
      syncContext,
    );
    // Resource metadata writes create durable per-document retry jobs. Commit
    // the metadata versions and cursor before any encrypted blob hydration so
    // an announcement or itinerary update can publish immediately even while a
    // large document is downloading, retrying, or unavailable.
    const syncedAt = manifest.server_time;
    await finalizeSyncState(
      tripId,
      cursor,
      manifest.trip.access_generation,
      syncedAt,
      manifest.versions,
      syncContext,
    );
    try {
      await acknowledgeCommittedSync({
        accessGeneration: manifest.trip.access_generation,
        cursor,
        path: '/mobile/sync/ack',
        syncContext,
        tripId,
        versions: manifest.versions,
      });
    } catch (error) {
      if (isSyncContextChanged(error)) assertSyncContextActive(syncContext);
      // Acknowledgements are telemetry only; the durable local cursor remains authoritative.
    }
    assertSyncContextActive(syncContext);
    await drainDurableSyncQueues(tripId, role, syncContext);
    return {
      tripId,
      cursor,
      changes: changeCount,
      changed: hasActualSyncChanges({
        baseline,
        changeCount,
        resourceChanges: versionChanged,
      }),
      syncedAt,
      documentPrefetch: null,
    };
  } catch (error) {
    if (isSyncContextChanged(error) || syncContext.signal.aborted) {
      assertSyncContextActive(syncContext);
    }
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
      await purgeTripCache(tripId, syncContext, 'authorization_denied').catch((purgeError: unknown) => {
        if (isSyncContextChanged(purgeError)) throw purgeError;
      });
    }
    await storeSyncFailure(tripId, error, syncContext).catch((storageError: unknown) => {
      if (isSyncContextChanged(storageError)) throw storageError;
      // Diagnostics are best effort and must never replace the synchronization failure.
    });
    throw error;
  }
}

function syncTripWithContext(
  tripId: string,
  syncContext: ImmutableSyncContext,
): Promise<SyncResult> {
  assertSyncContextActive(syncContext);
  const key = `${syncContext.namespace}:${syncContext.sessionId}:${syncContext.principalId}:${tripId}`;
  return tripSyncTasks.run(key, async (sharedSignal) => {
    const workerLease = captureSyncContext(sharedSignal);
    try {
      if (!sameSyncIdentity(syncContext, workerLease.context)) {
        throw new SyncContextChangedError();
      }
      return await performTripSync(tripId, workerLease.context);
    } finally {
      workerLease.release();
    }
  }, syncContext.signal);
}

/**
 * Synchronizes one trip inside an already captured authentication boundary.
 *
 * Long-lived background lanes must retain the account context that selected
 * their trip identifiers. Capturing a fresh context for every queued item
 * could otherwise let an old account's trip identifier cross a concurrent
 * account switch before the next worker starts.
 */
export function syncTripInContext(
  tripId: string,
  syncContext: ImmutableSyncContext,
  options: SyncTripOptions = {},
): Promise<SyncResult> {
  assertSyncContextActive(syncContext);
  return syncTripWithContext(tripId, syncContext).then(async (result) => {
    assertSyncContextActive(syncContext);
    if (options.documentHydration === 'background') {
      runBackgroundDocumentHydration(tripId, syncContext);
      return result;
    }
    const documentPrefetch = await hydrateDocuments(
      tripId,
      syncContext,
      options.onDocumentProgress,
    );
    assertSyncContextActive(syncContext);
    return { ...result, documentPrefetch };
  });
}

export function syncTrip(tripId: string, options: SyncTripOptions = {}): Promise<SyncResult> {
  const lease = captureSyncContext(options.signal);
  return syncTripInContext(tripId, lease.context, options)
    .finally(lease.release);
}

async function syncTripsBounded(
  trips: Trip[],
  syncContext: ImmutableSyncContext,
): Promise<Pick<SyncAllTripsSummary, 'results' | 'failures'>> {
  if (trips.length === 0) return { results: [], failures: [] };
  const results: (SyncResult | null)[] = Array.from({ length: trips.length }, () => null);
  const failures: (SyncTripFailure | null)[] = Array.from({ length: trips.length }, () => null);
  let nextIndex = 0;
  const worker = async (): Promise<void> => {
    while (true) {
      assertSyncContextActive(syncContext);
      const index = nextIndex;
      if (index >= trips.length) return;
      nextIndex += 1;
      const trip = trips[index];
      if (!trip) continue;
      try {
        results[index] = await syncTripWithContext(trip.id, syncContext);
        runBackgroundDocumentHydration(trip.id, syncContext);
      } catch (error) {
        if (isSyncContextChanged(error) || syncContext.signal.aborted) {
          assertSyncContextActive(syncContext);
        }
        // One revoked or temporarily failing trip must not prevent other assigned
        // trips from refreshing. Preserve a PII-free, ordered result so callers
        // can distinguish partial and total failure without parsing messages.
        failures[index] = syncTripFailure(trip.id, error);
      }
    }
  };
  const workerCount = Math.min(FULL_SYNC_CONCURRENCY, trips.length);
  await Promise.all(Array.from({ length: workerCount }, () => worker()));
  assertSyncContextActive(syncContext);
  return {
    results: results.filter((result): result is SyncResult => result !== null),
    failures: failures.filter((failure): failure is SyncTripFailure => failure !== null),
  };
}

export function prioritizeTripsForSync(
  trips: readonly Trip[],
  selectedTripId: string | null,
): Trip[] {
  if (!selectedTripId) return [...trips];
  const selected = trips.find((trip) => trip.id === selectedTripId);
  if (!selected) return [...trips];
  return [selected, ...trips.filter((trip) => trip.id !== selectedTripId)];
}

async function performFullSync(syncContext: ImmutableSyncContext): Promise<SyncAllTripsSummary> {
  let previousTrips: Trip[];
  try {
    previousTrips = await localTripsInContext(syncContext);
  } catch (error) {
    if (isSyncContextChanged(error) || syncContext.signal.aborted) {
      assertSyncContextActive(syncContext);
    }
    previousTrips = [];
  }
  const refreshed = await refreshTripsInContext(syncContext);
  const trips = prioritizeTripsForSync(
    refreshed.trips,
    useSelectedTripStore.getState().tripId,
  );
  recordMobileMetric('queue_depth', trips.length, { queue: 'sync' });
  const outcome = await syncTripsBounded(trips, syncContext).finally(() => {
    recordMobileMetric('queue_depth', 0, { queue: 'sync' });
  });
  assertSyncContextActive(syncContext);
  return {
    results: outcome.results,
    failures: outcome.failures,
    requestedTripCount: refreshed.trips.length,
    tripsChanged: tripCollectionsDiffer(previousTrips, refreshed.trips),
    removedTripIds: previousTrips
      .filter((trip) => !refreshed.trips.some((current) => current.id === trip.id))
      .map((trip) => trip.id),
  };
}

export function syncAllTripsWithSummary(
  options: SyncAllTripsOptions = {},
): Promise<SyncAllTripsSummary> {
  const lease = captureSyncContext(options.signal);
  const { context: syncContext } = lease;
  const key = `${syncContext.namespace}:${syncContext.sessionId}:${syncContext.principalId}`;
  return fullSyncTasks.run(key, async (sharedSignal) => {
    const workerLease = captureSyncContext(sharedSignal);
    const startedAtMs = performance.now();
    let outcome: MobileMetricAttributes['outcome'] = 'failure';
    try {
      if (!sameSyncIdentity(syncContext, workerLease.context)) {
        throw new SyncContextChangedError();
      }
      const summary = await performFullSync(workerLease.context);
      outcome = summary.failures.length > 0 ? 'partial' : 'success';
      return summary;
    } catch (error) {
      outcome = workerLease.context.signal.aborted ? 'cancelled' : 'failure';
      throw error;
    } finally {
      recordMobileMetric('sync_duration', performance.now() - startedAtMs, { outcome });
      recordMobileMetric('sync_run', 1, { outcome });
      workerLease.release();
    }
  }, syncContext.signal).finally(lease.release);
}

export async function syncAllTrips(
  options: SyncAllTripsOptions = {},
): Promise<SyncAllTripsSummary> {
  return syncAllTripsWithSummary(options);
}

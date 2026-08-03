import { ApiError, apiRequest } from '@/core/api/client';
import {
  ManifestSchema,
  SyncAckResponseSchema,
  SyncPageSchema,
  type SyncChangeSchema,
} from '@/core/api/contracts';
import type { MobileRole } from '@/core/auth/types';
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
import { tripCollectionsDiffer } from './sync-runtime-policy';
import {
  assertSyncContextActive,
  captureSyncContext,
  isSyncContextChanged,
  type ImmutableSyncContext,
} from './sync-context';

const MAX_SYNC_PAGES = 20;
const SYNC_PAGE_SIZE = 500;
const FULL_SYNC_CONCURRENCY = 2;
const syncInFlight = new Map<string, Promise<SyncResult>>();
const fullSyncInFlight = new Map<string, Promise<SyncAllTripsSummary>>();

type SyncChange = z.infer<typeof SyncChangeSchema>;
export type SyncResult = {
  tripId: string;
  cursor: number;
  changes: number;
  changed: boolean;
  syncedAt: string;
  documentPrefetch: OfflinePrefetchProgress | null;
};

export type SyncTripOptions = {
  onDocumentProgress?: (progress: OfflinePrefetchProgress) => void;
};

export type SyncAllTripsSummary = {
  results: SyncResult[];
  failures: SyncTripFailure[];
  requestedTripCount: number;
  tripsChanged: boolean;
  removedTripIds: string[];
};

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
      (id, account_namespace, agency_id, role, name, destination, travel_date, return_date,
       access_generation, access_expires_at,
       itinerary_version, common_document_version, personal_document_version,
       announcement_version, readiness_version, roster_version, rooming_version,
       meals_version, qr_version,
       advertised_itinerary_version, advertised_common_document_version,
       advertised_personal_document_version, advertised_announcement_version,
       advertised_readiness_version, advertised_roster_version,
       advertised_rooming_version, advertised_meals_version, advertised_qr_version,
       updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, -1, -1, -1, -1, -1, -1, -1, -1, -1,
       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(id) DO UPDATE SET
       role = excluded.role, name = excluded.name, destination = excluded.destination,
       travel_date = excluded.travel_date, return_date = excluded.return_date,
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
  syncContext: ImmutableSyncContext,
): Promise<void> {
  assertSyncContextActive(syncContext);
  const requests: Promise<unknown>[] = [];
  const optional = (request: Promise<unknown>) => request.catch((error: unknown) => {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  });
  if ((baseline && versions.itinerary > 0) || flags.itinerary) requests.push(optional(refreshItinerary(tripId, syncContext)));
  if ((baseline && versions.announcements > 0) || flags.announcements) requests.push(optional(refreshAnnouncements(tripId, syncContext)));
  if ((baseline && versions.common_documents > 0) || flags.documents) requests.push(optional(refreshCommonDocuments(tripId, syncContext)));
  if (role === 'passenger') {
    if (baseline || flags.documents) requests.push(optional(refreshDocuments(tripId, syncContext)));
    if ((baseline && versions.rooming > 0) || flags.room) requests.push(optional(loadRoom(tripId, syncContext)));
    if ((baseline && versions.meals > 0) || flags.meals) requests.push(optional(loadMeal(tripId, syncContext)));
    if ((baseline && versions.qr > 0) || flags.qr) requests.push(optional(refreshQr(tripId, syncContext)));
  } else if (role === 'client_manager') {
    if (baseline || flags.readiness) requests.push(optional(loadReadiness(tripId, syncContext)));
  } else {
    if (baseline || flags.roster || flags.room || flags.meals) requests.push(optional(syncFullRoster(tripId, syncContext)));
    else if (flags.passengerChanges.length) {
      requests.push(applyCoordinatorPassengerChanges(tripId, flags.passengerChanges, syncContext));
    }
    if (baseline || flags.roster || flags.attendance) requests.push(optional(loadAttendanceSummary(tripId, syncContext)));
  }
  await Promise.all(requests);
  assertSyncContextActive(syncContext);
}

async function performTripSync(
  tripId: string,
  syncContext: ImmutableSyncContext,
  options: SyncTripOptions = {},
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
    resourcePath(manifest.resources.sync_changes);
    const syncPath = '/mobile/sync/changes';
    while (true) {
      assertSyncContextActive(syncContext);
      if (pages >= MAX_SYNC_PAGES) throw new Error('Synchronization exceeded its bounded page limit.');
      const query = new URLSearchParams({ trip_id: tripId, cursor: String(cursor), limit: String(SYNC_PAGE_SIZE) });
      const page = await apiRequest(`${syncPath}?${query.toString()}`, {
        schema: SyncPageSchema,
        signal: syncContext.signal,
      });
      assertSyncContextActive(syncContext);
      assertCursorAdvance(cursor, page.next_cursor, page.has_more);
      let sequence = cursor;
      for (const change of page.changes) {
        if (change.group_id !== tripId || change.sequence <= sequence) throw new Error('Synchronization changes were out of scope or order.');
        sequence = change.sequence;
        aggregate.push(change);
      }
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
      syncContext,
    );
    let documentPrefetch: OfflinePrefetchProgress | null = null;
    if (role === 'passenger') {
      // Metadata synchronization stays compact; only new or replaced passenger/common files
      // are encrypted into this account's private vault. Individual file
      // failures are already converted into the bounded outcome by the
      // prefetcher; a structural database/context failure must propagate and
      // fail closed instead of advancing the durable cursor.
      documentPrefetch = await prefetchPassengerOfflineDocuments(
        tripId,
        options.onDocumentProgress,
        syncContext,
      );
    } else {
      // Common documents are part of the offline contract for managers and
      // coordinators too. Run the same version-aware vault reconciliation after
      // every successful metadata pass: unchanged files are a local no-op,
      // while an earlier interrupted download receives another bounded retry.
      documentPrefetch = await prefetchCommonOfflineDocuments(
        tripId,
        options.onDocumentProgress,
        syncContext,
      );
    }
    // Metadata and its durable per-document retry jobs are committed before
    // this point. A blob failure remains visible in documentPrefetch but must
    // not replay the already-applied change page or prevent cursor/version
    // finalization; the next due cycle retries only that document job.
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
      const acknowledgement = await apiRequest('/mobile/sync/ack', {
        method: 'POST',
        body: {
          trip_id: tripId,
          cursor,
          access_generation: manifest.trip.access_generation,
          versions: manifest.versions,
        },
        schema: SyncAckResponseSchema,
        signal: syncContext.signal,
      });
      assertSyncContextActive(syncContext);
      if (
        acknowledgement.trip_id !== tripId ||
        acknowledgement.cursor !== cursor ||
        acknowledgement.access_generation !== manifest.trip.access_generation
      ) {
        throw new Error('The synchronization acknowledgement was out of scope.');
      }
    } catch (error) {
      if (isSyncContextChanged(error)) assertSyncContextActive(syncContext);
      // Acknowledgements are telemetry only; the durable local cursor remains authoritative.
    }
    assertSyncContextActive(syncContext);
    const durableQueues: Promise<unknown>[] = [drainNotificationReads(tripId)];
    if (role === 'coordinator') {
      durableQueues.push(drainAttendanceQueue(tripId), drainIncidentQueue(tripId));
    }
    await Promise.all(durableQueues.map((request) => request.catch(() => undefined)));
    assertSyncContextActive(syncContext);
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
      documentPrefetch,
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
  options: SyncTripOptions = {},
): Promise<SyncResult> {
  assertSyncContextActive(syncContext);
  const key = `${syncContext.namespace}:${syncContext.sessionId}:${syncContext.principalId}:${tripId}`;
  const active = syncInFlight.get(key);
  if (active) return active;
  const request = performTripSync(tripId, syncContext, options).finally(() => {
    if (syncInFlight.get(key) === request) syncInFlight.delete(key);
  });
  syncInFlight.set(key, request);
  return request;
}

export function syncTrip(tripId: string, options: SyncTripOptions = {}): Promise<SyncResult> {
  const lease = captureSyncContext();
  return syncTripWithContext(tripId, lease.context, options).finally(lease.release);
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
  const outcome = await syncTripsBounded(refreshed.trips, syncContext);
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

export function syncAllTripsWithSummary(): Promise<SyncAllTripsSummary> {
  const lease = captureSyncContext();
  const { context: syncContext } = lease;
  const key = `${syncContext.namespace}:${syncContext.sessionId}:${syncContext.principalId}`;
  const active = fullSyncInFlight.get(key);
  if (active) {
    lease.release();
    return active;
  }
  const request = performFullSync(syncContext).finally(() => {
    if (fullSyncInFlight.get(key) === request) fullSyncInFlight.delete(key);
    lease.release();
  });
  fullSyncInFlight.set(key, request);
  return request;
}

export async function syncAllTrips(): Promise<SyncAllTripsSummary> {
  return syncAllTripsWithSummary();
}

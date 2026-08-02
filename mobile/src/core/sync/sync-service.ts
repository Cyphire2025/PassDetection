import { ApiError, apiRequest } from '@/core/api/client';
import {
  ManifestSchema,
  SyncAckResponseSchema,
  SyncPageSchema,
  type SyncChangeSchema,
} from '@/core/api/contracts';
import { accountNamespace, type MobileRole } from '@/core/auth/types';
import { useSessionStore } from '@/core/auth/session-store';
import { openAccountDatabase } from '@/core/storage/database';
import { refreshAnnouncements, refreshCommonDocuments, refreshDocuments, refreshQr, loadMeal, loadReadiness, loadRoom } from '@/features/content/data/content-repository';
import { refreshItinerary } from '@/features/content/data/itinerary-repository';
import {
  applyCoordinatorPassengerChanges,
  loadAttendanceSummary,
  syncFullRoster,
} from '@/features/coordinator/data/coordinator-repository';
import { drainAttendanceQueue } from '@/features/coordinator/data/attendance-queue';
import { drainIncidentQueue } from '@/features/coordinator/data/operations-repository';
import { drainNotificationReads } from '@/features/notifications/data/notification-repository';
import { refreshTrips } from '@/features/trips/data/trip-repository';
import type { z } from 'zod';

import { purgeTripCache, resetTripCache } from './access-cache';
import { assertCursorAdvance, resourceVersionChanges } from './sync-policy';

const MAX_SYNC_PAGES = 20;
const SYNC_PAGE_SIZE = 500;
const syncInFlight = new Map<string, Promise<SyncResult>>();

type SyncChange = z.infer<typeof SyncChangeSchema>;
export type SyncResult = { tripId: string; cursor: number; changes: number; syncedAt: string };

function context() {
  const principal = useSessionStore.getState().session?.principal;
  if (!principal) throw new Error('Authentication is required.');
  return {
    namespace: accountNamespace({ agencyId: principal.agencyId, principalId: principal.id }),
    role: principal.principalType,
    agencyId: principal.agencyId,
  };
}

function resourcePath(value: string): string {
  const prefix = '/api/v1';
  if (!value.startsWith(`${prefix}/mobile/`) || value.includes('://')) {
    throw new Error('The manifest contained an invalid mobile resource path.');
  }
  return value.slice(prefix.length);
}

async function localTripState(tripId: string) {
  const { namespace } = context();
  const database = await openAccountDatabase(namespace);
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
  return { trip, cursor: cursor?.cursor ?? 0 };
}

async function storeManifest(tripId: string, manifest: z.infer<typeof ManifestSchema>): Promise<void> {
  const { namespace, agencyId } = context();
  const database = await openAccountDatabase(namespace);
  await database.runAsync(
    `INSERT INTO trips
      (id, account_namespace, agency_id, role, name, destination, travel_date, return_date,
       access_generation, access_expires_at, itinerary_version, common_document_version,
       personal_document_version, announcement_version, readiness_version, roster_version,
       rooming_version, meals_version, qr_version, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(id) DO UPDATE SET
       role = excluded.role, name = excluded.name, destination = excluded.destination,
       travel_date = excluded.travel_date, return_date = excluded.return_date,
       access_generation = excluded.access_generation, access_expires_at = excluded.access_expires_at,
       itinerary_version = excluded.itinerary_version,
       common_document_version = excluded.common_document_version,
       personal_document_version = excluded.personal_document_version,
       announcement_version = excluded.announcement_version,
       readiness_version = excluded.readiness_version,
       roster_version = excluded.roster_version,
       rooming_version = excluded.rooming_version,
       meals_version = excluded.meals_version,
       qr_version = excluded.qr_version,
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
    manifest.trip.itinerary_version,
    manifest.trip.common_document_version,
    manifest.versions.personal_documents,
    manifest.trip.announcement_version,
    manifest.versions.readiness,
    manifest.versions.roster,
    manifest.versions.rooming,
    manifest.versions.meals,
    manifest.versions.qr,
    manifest.server_time,
  );
}

async function storeCursor(tripId: string, cursor: number, accessGeneration: number, syncedAt: string) {
  const { namespace } = context();
  const database = await openAccountDatabase(namespace);
  await database.runAsync(
    `INSERT INTO sync_cursors (account_namespace, trip_id, cursor, access_generation, last_synced_at, last_error_code)
     VALUES (?, ?, ?, ?, ?, NULL)
     ON CONFLICT(account_namespace, trip_id) DO UPDATE SET
       cursor = excluded.cursor, access_generation = excluded.access_generation,
       last_synced_at = excluded.last_synced_at, last_error_code = NULL`,
    namespace, tripId, cursor, accessGeneration, syncedAt,
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

async function refreshChangedResources(
  tripId: string,
  role: MobileRole,
  flags: ReturnType<typeof changeFlags>,
  baseline: boolean,
  versions: z.infer<typeof ManifestSchema>['versions'],
): Promise<void> {
  const requests: Promise<unknown>[] = [];
  const optional = (request: Promise<unknown>) => request.catch((error: unknown) => {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  });
  if ((baseline && versions.itinerary > 0) || flags.itinerary) requests.push(optional(refreshItinerary(tripId)));
  if ((baseline && versions.announcements > 0) || flags.announcements) requests.push(optional(refreshAnnouncements(tripId)));
  if ((baseline && versions.common_documents > 0) || flags.documents) requests.push(optional(refreshCommonDocuments(tripId)));
  if (role === 'passenger') {
    if (baseline || flags.documents) requests.push(optional(refreshDocuments(tripId)));
    if ((baseline && versions.rooming > 0) || flags.room) requests.push(optional(loadRoom(tripId)));
    if ((baseline && versions.meals > 0) || flags.meals) requests.push(optional(loadMeal(tripId)));
    if ((baseline && versions.qr > 0) || flags.qr) requests.push(optional(refreshQr(tripId)));
  } else if (role === 'client_manager') {
    if (baseline || flags.readiness) requests.push(optional(loadReadiness(tripId)));
  } else {
    if (baseline || flags.roster || flags.room || flags.meals) requests.push(optional(syncFullRoster(tripId)));
    else if (flags.passengerChanges.length) {
      requests.push(applyCoordinatorPassengerChanges(tripId, flags.passengerChanges));
    }
    if (baseline || flags.roster || flags.attendance) requests.push(optional(loadAttendanceSummary(tripId)));
  }
  await Promise.all(requests);
}

async function performTripSync(tripId: string): Promise<SyncResult> {
  const { role } = context();
  try {
    const previous = await localTripState(tripId);
    const manifest = await apiRequest(`/mobile/trips/${tripId}/manifest`, { schema: ManifestSchema });
    if (manifest.trip.id !== tripId || manifest.trip.role !== role) {
      await purgeTripCache(tripId);
      throw new Error('The manifest identity did not match this workspace.');
    }
    const serverNow = Date.parse(manifest.server_time);
    const expiresAt = manifest.access_expires_at ? Date.parse(manifest.access_expires_at) : null;
    if (!Number.isFinite(serverNow) || (expiresAt !== null && (!Number.isFinite(expiresAt) || expiresAt <= serverNow))) {
      await purgeTripCache(tripId);
      throw new Error('Trip access has expired.');
    }
    if (previous.trip && previous.trip.access_generation !== manifest.trip.access_generation) {
      await resetTripCache(tripId, manifest.trip.access_generation);
      previous.cursor = 0;
    }
    await storeManifest(tripId, manifest);

    let cursor = previous.cursor > manifest.sync_cursor ? 0 : previous.cursor;
    let pages = 0;
    let changeCount = 0;
    const baseline = cursor === 0;
    const aggregate: SyncChange[] = [];
    resourcePath(manifest.resources.sync_changes);
    const syncPath = '/mobile/sync/changes';
    while (true) {
      if (pages >= MAX_SYNC_PAGES) throw new Error('Synchronization exceeded its bounded page limit.');
      const query = new URLSearchParams({ trip_id: tripId, cursor: String(cursor), limit: String(SYNC_PAGE_SIZE) });
      const page = await apiRequest(`${syncPath}?${query.toString()}`, { schema: SyncPageSchema });
      assertCursorAdvance(cursor, page.next_cursor, page.has_more);
      let sequence = cursor;
      for (const change of page.changes) {
        if (change.group_id !== tripId || change.sequence <= sequence) throw new Error('Synchronization changes were out of scope or order.');
        sequence = change.sequence;
        aggregate.push(change);
      }
      const flags = changeFlags(page.changes);
      if (flags.revoke) {
        await purgeTripCache(tripId);
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
    await refreshChangedResources(tripId, role, {
      ...flags,
      itinerary: flags.itinerary || versionChanged.itinerary,
      documents: flags.documents || versionChanged.commonDocuments || versionChanged.personalDocuments,
      announcements: flags.announcements || versionChanged.announcements,
      readiness: flags.readiness || versionChanged.readiness,
      roster: flags.roster || versionChanged.roster,
      room: flags.room || versionChanged.rooming,
      meals: flags.meals || versionChanged.meals,
      qr: flags.qr || versionChanged.qr,
    }, baseline, manifest.versions);
    const syncedAt = manifest.server_time;
    await storeCursor(tripId, cursor, manifest.trip.access_generation, syncedAt);
    await apiRequest('/mobile/sync/ack', {
      method: 'POST',
      body: {
        trip_id: tripId,
        cursor,
        access_generation: manifest.trip.access_generation,
        versions: manifest.versions,
      },
      schema: SyncAckResponseSchema,
    }).then((acknowledgement) => {
      if (
        acknowledgement.trip_id !== tripId ||
        acknowledgement.cursor !== cursor ||
        acknowledgement.access_generation !== manifest.trip.access_generation
      ) {
        throw new Error('The synchronization acknowledgement was out of scope.');
      }
    }).catch(() => undefined);
    const durableQueues: Promise<unknown>[] = [drainNotificationReads(tripId)];
    if (role === 'coordinator') {
      durableQueues.push(drainAttendanceQueue(tripId), drainIncidentQueue(tripId));
    }
    await Promise.all(durableQueues.map((request) => request.catch(() => undefined)));
    return { tripId, cursor, changes: changeCount, syncedAt };
  } catch (error) {
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
      await purgeTripCache(tripId).catch(() => undefined);
    }
    throw error;
  }
}

export function syncTrip(tripId: string): Promise<SyncResult> {
  const { namespace } = context();
  const key = `${namespace}:${tripId}`;
  const active = syncInFlight.get(key);
  if (active) return active;
  const request = performTripSync(tripId).finally(() => {
    if (syncInFlight.get(key) === request) syncInFlight.delete(key);
  });
  syncInFlight.set(key, request);
  return request;
}

export async function syncAllTrips(): Promise<SyncResult[]> {
  const refreshed = await refreshTrips();
  const results: SyncResult[] = [];
  for (const trip of refreshed.trips) {
    try {
      results.push(await syncTrip(trip.id));
    } catch {
      // One revoked or temporarily failing trip must not prevent other assigned trips from refreshing.
    }
  }
  return results;
}

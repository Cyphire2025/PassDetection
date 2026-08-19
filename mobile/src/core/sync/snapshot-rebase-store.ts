import type * as SQLite from 'expo-sqlite';
import type { ZodType } from 'zod';

import {
  ManifestSchema,
  type SyncSnapshot,
} from '@/core/api/contracts';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';
import {
  AnnouncementSchema,
  CommonDocumentSchema,
  DocumentMetadataSchema,
  ItinerarySchema,
  MealSchema,
  PersonalQrSchema,
  ReadinessSchema,
  RoomSchema,
  type DocumentMetadata,
} from '@/features/content/api/content-contracts';
import { shouldPrefetchPassengerDocument } from '@/features/content/data/passenger-document-policy';
import {
  AttendanceSessionSchema,
  CoordinatorPassengerSchema,
} from '@/features/coordinator/api/coordinator-contracts';
import { ManagerPassengerSchema } from '@/features/manager/api/manager-contracts';

import {
  assertSyncContextActive,
  type ImmutableSyncContext,
} from './sync-context';
import {
  snapshotVersionsEqual,
  type SnapshotResourceName,
} from './snapshot-rebase-contract';

const PROMOTION_READ_BATCH_SIZE = 200;
const ROSTER_WRITE_BATCH_SIZE = 60;
export const SNAPSHOT_STAGE_WRITE_BATCH_SIZE = 100;
const SQLITE_WRITE_VARIABLE_BUDGET = 900;

type ActiveAssertion = () => void;

function sqliteWriteBatches<T>(items: readonly T[], bindingsPerRow: number): readonly (readonly T[])[] {
  if (!Number.isSafeInteger(bindingsPerRow) || bindingsPerRow < 1) {
    throw new Error('The SQLite write binding count was invalid.');
  }
  const batchSize = Math.floor(SQLITE_WRITE_VARIABLE_BUDGET / bindingsPerRow);
  if (batchSize < 1) throw new Error('A SQLite row exceeded the write variable budget.');
  const batches: T[][] = [];
  for (let offset = 0; offset < items.length; offset += batchSize) {
    batches.push(items.slice(offset, offset + batchSize));
  }
  return batches;
}

export type SnapshotStageIdentity = Readonly<{
  generationId: string;
  namespace: string;
  tripId: string;
}>;

export type SnapshotStageItem = Readonly<{
  key: string;
  payload: unknown;
}>;

type StageRow = Readonly<{
  item_index: number;
  payload_json: string;
}>;

function parseStaged<T>(schema: ZodType<T>, payloadJson: string): T {
  let raw: unknown;
  try {
    raw = JSON.parse(payloadJson) as unknown;
  } catch {
    throw new Error('The staged snapshot metadata was malformed.');
  }
  const parsed = schema.safeParse(raw);
  if (!parsed.success) throw new Error('The staged snapshot metadata failed validation.');
  return parsed.data;
}

async function forEachStagedBatch<T>(
  transaction: SQLite.SQLiteDatabase,
  stage: SnapshotStageIdentity,
  resource: SnapshotResourceName,
  schema: ZodType<T>,
  operation: (items: readonly T[]) => Promise<void>,
  assertActive?: ActiveAssertion,
): Promise<number> {
  let lastIndex = -1;
  let expectedIndex = 0;
  while (true) {
    assertActive?.();
    const rows = await transaction.getAllAsync<StageRow>(
      `SELECT item_index, payload_json
         FROM sync_rebase_staging
        WHERE account_namespace = ? AND trip_id = ? AND generation_id = ?
          AND resource_type = ? AND item_index > ?
        ORDER BY item_index
        LIMIT ?`,
      stage.namespace,
      stage.tripId,
      stage.generationId,
      resource,
      lastIndex,
      PROMOTION_READ_BATCH_SIZE,
    );
    assertActive?.();
    if (rows.length === 0) return expectedIndex;
    const items: T[] = [];
    for (const row of rows) {
      if (row.item_index !== expectedIndex) {
        throw new Error('The staged snapshot page sequence was incomplete.');
      }
      items.push(parseStaged(schema, row.payload_json));
      lastIndex = row.item_index;
      expectedIndex += 1;
    }
    assertActive?.();
    await operation(items);
    assertActive?.();
  }
}

async function stagedSingleton<T>(
  transaction: SQLite.SQLiteDatabase,
  stage: SnapshotStageIdentity,
  resource: SnapshotResourceName,
  schema: ZodType<T>,
  assertActive?: ActiveAssertion,
): Promise<T | null> {
  let value: T | null = null;
  const count = await forEachStagedBatch(
    transaction,
    stage,
    resource,
    schema,
    async (items) => {
      if (value !== null || items.length !== 1) {
        throw new Error('The staged singleton resource contained multiple values.');
      }
      value = items[0] ?? null;
    },
    assertActive,
  );
  if (count > 1) throw new Error('The staged singleton resource contained multiple values.');
  return value;
}

export async function beginSnapshotStage(
  stage: SnapshotStageIdentity,
  syncContext: ImmutableSyncContext,
): Promise<void> {
  assertSyncContextActive(syncContext);
  const database = await openAccountDatabase(stage.namespace);
  assertSyncContextActive(syncContext);
  await withAccountTransaction(database, async (transaction) => {
    const assertActive = () => assertSyncContextActive(syncContext);
    assertActive();
    await transaction.runAsync(
      'DELETE FROM sync_rebase_staging WHERE account_namespace = ? AND trip_id = ?',
      stage.namespace,
      stage.tripId,
    );
  });
}

export async function stageSnapshotPage(
  stage: SnapshotStageIdentity,
  resource: SnapshotResourceName,
  startIndex: number,
  items: readonly SnapshotStageItem[],
  syncContext: ImmutableSyncContext,
): Promise<number> {
  if (!Number.isSafeInteger(startIndex) || startIndex < 0) {
    throw new Error('The snapshot staging offset was invalid.');
  }
  assertSyncContextActive(syncContext);
  if (items.length === 0) return startIndex;
  const database = await openAccountDatabase(stage.namespace);
  assertSyncContextActive(syncContext);
  await withAccountTransaction(database, async (transaction) => {
    for (let batchOffset = 0; batchOffset < items.length; batchOffset += SNAPSHOT_STAGE_WRITE_BATCH_SIZE) {
      assertSyncContextActive(syncContext);
      const batch = items.slice(batchOffset, batchOffset + SNAPSHOT_STAGE_WRITE_BATCH_SIZE);
      const parameters: (number | string)[] = [];
      for (const [itemOffset, item] of batch.entries()) {
        const payloadJson = JSON.stringify(item.payload);
        if (typeof payloadJson !== 'string') {
          throw new Error('The snapshot staging payload was not serializable.');
        }
        const itemIndex = startIndex + batchOffset + itemOffset;
        if (!Number.isSafeInteger(itemIndex)) {
          throw new Error('The snapshot staging offset exceeded a safe integer.');
        }
        parameters.push(
          stage.namespace,
          stage.tripId,
          stage.generationId,
          resource,
          item.key,
          itemIndex,
          payloadJson,
        );
      }
      const values = batch.map(() => '(?, ?, ?, ?, ?, ?, ?)').join(', ');
      const saved = await transaction.runAsync(
        `INSERT INTO sync_rebase_staging
          (account_namespace, trip_id, generation_id, resource_type,
           item_key, item_index, payload_json)
         VALUES ${values}`,
        parameters,
      );
      if (saved.changes !== batch.length) {
        throw new Error('The snapshot staging batch was incomplete.');
      }
    }
  });
  return startIndex + items.length;
}

export async function discardSnapshotStage(
  stage: SnapshotStageIdentity,
  syncContext: ImmutableSyncContext,
): Promise<void> {
  assertSyncContextActive(syncContext);
  const database = await openAccountDatabase(stage.namespace);
  assertSyncContextActive(syncContext);
  await database.runAsync(
    `DELETE FROM sync_rebase_staging
      WHERE account_namespace = ? AND trip_id = ? AND generation_id = ?`,
    stage.namespace,
    stage.tripId,
    stage.generationId,
  );
}

async function replaceItinerary(
  transaction: SQLite.SQLiteDatabase,
  stage: SnapshotStageIdentity,
  assertActive?: ActiveAssertion,
): Promise<void> {
  const itinerary = await stagedSingleton(
    transaction,
    stage,
    'itinerary',
    ItinerarySchema,
    assertActive,
  );
  assertActive?.();
  await transaction.runAsync(
    'DELETE FROM itinerary_days WHERE account_namespace = ? AND trip_id = ?',
    stage.namespace,
    stage.tripId,
  );
  if (!itinerary) return;
  for (const batch of sqliteWriteBatches(itinerary.days, 8)) {
    assertActive?.();
    const values = batch.map(() => '(?, ?, ?, ?, ?, ?, ?, ?)').join(', ');
    await transaction.runAsync(
      `INSERT INTO itinerary_days
        (id, account_namespace, trip_id, version, day_number, calendar_date, title, sort_order)
       VALUES ${values}`,
      batch.flatMap((day) => [
        day.id,
        stage.namespace,
        stage.tripId,
        itinerary.version,
        day.day_number,
        day.date,
        day.title,
        day.sort_order,
      ]),
    );
  }
  const itineraryItems = itinerary.days.flatMap((day) => (
    day.items.map((item) => ({ dayId: day.id, item }))
  ));
  for (const batch of sqliteWriteBatches(itineraryItems, 13)) {
    assertActive?.();
    const values = batch.map(() => '(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)').join(', ');
    await transaction.runAsync(
      `INSERT INTO itinerary_items
        (id, account_namespace, trip_id, day_id, version, title, description, starts_at,
         ends_at, location_name, latitude, longitude, sort_order)
       VALUES ${values}`,
      batch.flatMap(({ dayId, item }) => [
        item.id,
        stage.namespace,
        stage.tripId,
        dayId,
        itinerary.version,
        item.title,
        item.description,
        item.starts_at,
        item.ends_at,
        item.location_name,
        item.latitude,
        item.longitude,
        item.sort_order,
      ]),
    );
  }
}

async function replaceAnnouncements(
  transaction: SQLite.SQLiteDatabase,
  stage: SnapshotStageIdentity,
  assertActive?: ActiveAssertion,
): Promise<void> {
  await forEachStagedBatch(
    transaction,
    stage,
    'announcements',
    AnnouncementSchema,
    async (items) => {
      for (const batch of sqliteWriteBatches(items, 10)) {
        assertActive?.();
        const values = batch.map(() => '(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)').join(', ');
        const saved = await transaction.runAsync(
          `INSERT INTO announcements
            (id, account_namespace, trip_id, version, title, message, priority,
             published_at, available_until, is_read)
           VALUES ${values}
           ON CONFLICT(id) DO UPDATE SET
             version = excluded.version, title = excluded.title, message = excluded.message,
             priority = excluded.priority, published_at = excluded.published_at,
             available_until = excluded.available_until,
             is_read = CASE WHEN announcements.is_read = 1 OR excluded.is_read = 1 THEN 1 ELSE 0 END
           WHERE announcements.account_namespace = excluded.account_namespace
             AND announcements.trip_id = excluded.trip_id`,
          batch.flatMap((item) => [
            item.id,
            stage.namespace,
            stage.tripId,
            item.version,
            item.title,
            item.message,
            item.priority,
            item.published_at,
            item.available_until,
            item.is_read ? 1 : 0,
          ]),
        );
        if (saved.changes !== batch.length) {
          throw new Error('An announcement crossed its trip boundary.');
        }
      }
    },
    assertActive,
  );
  assertActive?.();
  await transaction.runAsync(
    `DELETE FROM announcements
      WHERE account_namespace = ? AND trip_id = ?
        AND NOT EXISTS (
          SELECT 1 FROM sync_rebase_staging staged
           WHERE staged.account_namespace = announcements.account_namespace
             AND staged.trip_id = announcements.trip_id
             AND staged.generation_id = ?
             AND staged.resource_type = 'announcements'
             AND staged.item_key = announcements.id
        )`,
    stage.namespace,
    stage.tripId,
    stage.generationId,
  );
}

async function upsertDocuments(
  transaction: SQLite.SQLiteDatabase,
  stage: SnapshotStageIdentity,
  documents: readonly DocumentMetadata[],
  nowIso: string,
  assertActive?: ActiveAssertion,
): Promise<void> {
  for (const batch of sqliteWriteBatches(documents, 15)) {
    assertActive?.();
    const values = batch.map(() => '(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)').join(', ');
    const saved = await transaction.runAsync(
      `INSERT INTO document_metadata
        (id, account_namespace, trip_id, passenger_id, scope, category, display_name,
         content_type, size_bytes, version, checksum_sha256, offline_available,
         metadata_state, updated_at, revoked_at)
       VALUES ${values}
       ON CONFLICT(id) DO UPDATE SET
         passenger_id = excluded.passenger_id, scope = excluded.scope,
         category = excluded.category, display_name = excluded.display_name,
         content_type = excluded.content_type, size_bytes = excluded.size_bytes,
         version = excluded.version, checksum_sha256 = excluded.checksum_sha256,
         offline_available = excluded.offline_available,
         metadata_state = excluded.metadata_state, updated_at = excluded.updated_at,
         revoked_at = excluded.revoked_at
       WHERE document_metadata.account_namespace = excluded.account_namespace
         AND document_metadata.trip_id = excluded.trip_id`,
      batch.flatMap((document) => [
        document.id,
        stage.namespace,
        stage.tripId,
        document.passenger_id,
        document.scope,
        document.category,
        document.display_name,
        document.content_type,
        document.size_bytes ?? 0,
        document.version,
        document.checksum_sha256 ?? '',
        document.offline_available ? 1 : 0,
        document.metadata_state,
        document.updated_at,
        document.revoked_at,
      ]),
    );
    if (saved.changes !== batch.length) {
      throw new Error('A document crossed its trip boundary.');
    }
  }

  const prefetch = documents.filter(shouldPrefetchPassengerDocument);
  for (const batch of sqliteWriteBatches(prefetch, 6)) {
    assertActive?.();
    const values = batch.map(() => '(?, ?, ?, ?, \'pending\', 0, NULL, NULL, ?, ?)').join(', ');
    const saved = await transaction.runAsync(
      `INSERT INTO offline_document_jobs
        (document_id, account_namespace, trip_id, version, state, attempt_count,
         next_attempt_at, last_error_code, created_at, updated_at)
       VALUES ${values}
       ON CONFLICT(document_id) DO UPDATE SET
         version = excluded.version,
         state = CASE WHEN offline_document_jobs.version <> excluded.version
                      THEN 'pending' ELSE offline_document_jobs.state END,
         attempt_count = CASE WHEN offline_document_jobs.version <> excluded.version
                              THEN 0 ELSE offline_document_jobs.attempt_count END,
         next_attempt_at = CASE WHEN offline_document_jobs.version <> excluded.version
                                THEN NULL ELSE offline_document_jobs.next_attempt_at END,
         last_error_code = CASE WHEN offline_document_jobs.version <> excluded.version
                                THEN NULL ELSE offline_document_jobs.last_error_code END,
         updated_at = excluded.updated_at
       WHERE offline_document_jobs.account_namespace = excluded.account_namespace
         AND offline_document_jobs.trip_id = excluded.trip_id`,
      batch.flatMap((document) => [
        document.id,
        stage.namespace,
        stage.tripId,
        document.version,
        nowIso,
        nowIso,
      ]),
    );
    if (saved.changes !== batch.length) {
      throw new Error('An offline document job crossed its trip boundary.');
    }
  }

  const withoutPrefetch = documents.filter((document) => !shouldPrefetchPassengerDocument(document));
  // Account and trip add two fixed bindings, so charging two bindings per row
  // keeps the complete statement comfortably below the same 900-variable budget.
  for (const batch of sqliteWriteBatches(withoutPrefetch, 2)) {
    assertActive?.();
    const placeholders = batch.map(() => '?').join(', ');
    await transaction.runAsync(
      `DELETE FROM offline_document_jobs
        WHERE account_namespace = ? AND trip_id = ?
          AND document_id IN (${placeholders})`,
      [stage.namespace, stage.tripId, ...batch.map((document) => document.id)],
    );
  }
}

async function replaceDocumentScope(
  transaction: SQLite.SQLiteDatabase,
  stage: SnapshotStageIdentity,
  resource: 'common_documents' | 'personal_documents',
  nowIso: string,
  assertActive?: ActiveAssertion,
): Promise<void> {
  const scope = resource === 'common_documents' ? 'common' : 'personal';
  if (scope === 'common') {
    await forEachStagedBatch(
      transaction,
      stage,
      resource,
      CommonDocumentSchema,
      async (items) => {
        await upsertDocuments(
          transaction,
          stage,
          items.map((item) => ({
            id: item.id,
            trip_id: item.trip_id,
            passenger_id: null,
            scope: 'common',
            category: item.category,
            display_name: item.title,
            content_type: item.media_type,
            size_bytes: item.byte_size,
            version: item.version,
            checksum_sha256: item.checksum_sha256,
            offline_available: item.offline_available,
            metadata_state: 'ready',
            updated_at: item.updated_at,
            revoked_at: null,
          })),
          nowIso,
          assertActive,
        );
      },
      assertActive,
    );
  } else {
    await forEachStagedBatch(
      transaction,
      stage,
      resource,
      DocumentMetadataSchema,
      async (items) => {
        await upsertDocuments(transaction, stage, items, nowIso, assertActive);
      },
      assertActive,
    );
  }

  assertActive?.();
  await transaction.runAsync(
    `DELETE FROM document_metadata
      WHERE account_namespace = ? AND trip_id = ? AND scope = ?
        AND NOT EXISTS (
          SELECT 1 FROM sync_rebase_staging staged
           WHERE staged.account_namespace = document_metadata.account_namespace
             AND staged.trip_id = document_metadata.trip_id
             AND staged.generation_id = ?
             AND staged.resource_type = ?
             AND staged.item_key = document_metadata.id
        )`,
    stage.namespace,
    stage.tripId,
    scope,
    stage.generationId,
    resource,
  );
}

async function replacePassengerSingletons(
  transaction: SQLite.SQLiteDatabase,
  stage: SnapshotStageIdentity,
  descriptor: SyncSnapshot,
  assertActive?: ActiveAssertion,
): Promise<void> {
  assertActive?.();
  await transaction.runAsync(
    'DELETE FROM room_assignments WHERE account_namespace = ? AND trip_id = ?',
    stage.namespace,
    stage.tripId,
  );
  await transaction.runAsync(
    'DELETE FROM meal_information WHERE account_namespace = ? AND trip_id = ?',
    stage.namespace,
    stage.tripId,
  );
  await transaction.runAsync(
    'DELETE FROM qr_metadata WHERE account_namespace = ? AND trip_id = ?',
    stage.namespace,
    stage.tripId,
  );
  if (descriptor.trip.role !== 'passenger') return;

  const room = await stagedSingleton(transaction, stage, 'room', RoomSchema, assertActive);
  if (room) {
    await transaction.runAsync(
      `INSERT INTO room_assignments
        (id, account_namespace, trip_id, passenger_id, hotel_name, room_number,
         roommate_summary, version, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      room.id,
      stage.namespace,
      stage.tripId,
      room.passenger_id,
      room.hotel_name,
      room.room_number,
      room.roommate_summary,
      room.version,
      room.updated_at,
    );
  }
  const meal = await stagedSingleton(transaction, stage, 'meals', MealSchema, assertActive);
  if (meal) {
    await transaction.runAsync(
      `INSERT INTO meal_information
        (id, account_namespace, trip_id, passenger_id, preference, notes, version, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
      meal.id,
      stage.namespace,
      stage.tripId,
      meal.passenger_id,
      meal.preference,
      meal.notes,
      meal.version,
      meal.updated_at,
    );
  }
  const qr = await stagedSingleton(transaction, stage, 'qr', PersonalQrSchema, assertActive);
  if (qr) {
    await transaction.runAsync(
      `INSERT INTO qr_metadata
        (id, account_namespace, trip_id, passenger_id, signed_payload, version,
         valid_from, valid_until, offline_allowed, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      qr.id,
      stage.namespace,
      stage.tripId,
      qr.passenger_id,
      qr.signed_payload,
      qr.version,
      qr.valid_from,
      qr.valid_until,
      qr.offline_allowed ? 1 : 0,
      qr.updated_at,
    );
  }
}

async function replaceReadiness(
  transaction: SQLite.SQLiteDatabase,
  stage: SnapshotStageIdentity,
  descriptor: SyncSnapshot,
  assertActive?: ActiveAssertion,
): Promise<void> {
  assertActive?.();
  await transaction.runAsync(
    'DELETE FROM manager_readiness WHERE account_namespace = ? AND trip_id = ?',
    stage.namespace,
    stage.tripId,
  );
  if (descriptor.trip.role !== 'client_manager') return;
  const readiness = await stagedSingleton(
    transaction,
    stage,
    'readiness',
    ReadinessSchema,
    assertActive,
  );
  if (!readiness) return;
  await transaction.runAsync(
    `INSERT INTO manager_readiness
      (account_namespace, trip_id, passenger_count, passports_complete, visas_available,
       tickets_available, items_needing_attention, rooms_assigned, meals_confirmed,
       version, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    stage.namespace,
    stage.tripId,
    readiness.passenger_count,
    readiness.passports_complete,
    readiness.visas_available,
    readiness.tickets_available,
    readiness.items_needing_attention,
    readiness.rooms_assigned,
    readiness.meals_confirmed,
    readiness.version,
    readiness.updated_at,
  );
}

async function replaceRoster(
  transaction: SQLite.SQLiteDatabase,
  stage: SnapshotStageIdentity,
  descriptor: SyncSnapshot,
  assertActive?: ActiveAssertion,
): Promise<void> {
  assertActive?.();
  if (descriptor.trip.role === 'passenger') {
    await transaction.runAsync(
      'DELETE FROM coordinator_passengers WHERE account_namespace = ? AND trip_id = ?',
      stage.namespace,
      stage.tripId,
    );
    return;
  }

  if (descriptor.trip.role === 'coordinator') {
    await forEachStagedBatch(
      transaction,
      stage,
      'roster',
      CoordinatorPassengerSchema,
      async (items) => {
        for (const batch of sqliteWriteBatches(items, 18)) {
          assertActive?.();
          const values = batch.map(
            () => '(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
          ).join(', ');
          const saved = await transaction.runAsync(
            `INSERT INTO coordinator_passengers
              (id, account_namespace, trip_id, display_name, employee_code, attendance_status,
               attendance_token_hash, attendance_token_version, attendance_token_state,
               attendance_token_expires_at, attendance_token_updated_at,
               attendance_evidence_observed_at, attendance_evidence_valid_until,
               room_number, meal_preference, has_alert, roster_version, updated_at)
             VALUES ${values}
             ON CONFLICT(account_namespace, trip_id, id) DO UPDATE SET
               display_name = excluded.display_name, employee_code = excluded.employee_code,
               attendance_status = excluded.attendance_status,
               attendance_token_hash = excluded.attendance_token_hash,
               attendance_token_version = excluded.attendance_token_version,
               attendance_token_state = excluded.attendance_token_state,
               attendance_token_expires_at = excluded.attendance_token_expires_at,
               attendance_token_updated_at = excluded.attendance_token_updated_at,
               attendance_evidence_observed_at = excluded.attendance_evidence_observed_at,
               attendance_evidence_valid_until = excluded.attendance_evidence_valid_until,
               room_number = excluded.room_number,
               meal_preference = excluded.meal_preference, has_alert = excluded.has_alert,
               roster_version = excluded.roster_version, updated_at = excluded.updated_at`,
            batch.flatMap((item) => [
              item.id,
              stage.namespace,
              stage.tripId,
              item.display_name,
              item.employee_code,
              item.attendance_status,
              item.attendance_token?.token_hash ?? null,
              item.attendance_token?.token_version ?? null,
              item.attendance_token?.state ?? 'unknown',
              item.attendance_token?.token_expires_at ?? null,
              item.attendance_token?.token_updated_at ?? null,
              item.attendance_token?.evidence_observed_at ?? null,
              item.attendance_token?.evidence_valid_until ?? null,
              item.room_number,
              item.meal_preference,
              item.has_alert ? 1 : 0,
              descriptor.versions.roster,
              descriptor.server_time,
            ]),
          );
          if (saved.changes !== batch.length) {
            throw new Error('A coordinator roster row crossed its trip boundary.');
          }
        }
      },
      assertActive,
    );
  } else {
    await forEachStagedBatch(
      transaction,
      stage,
      'roster',
      ManagerPassengerSchema,
        async (items) => {
          for (let offset = 0; offset < items.length; offset += ROSTER_WRITE_BATCH_SIZE) {
            assertActive?.();
            const batch = items.slice(offset, offset + ROSTER_WRITE_BATCH_SIZE);
            const values = batch.map(() => '(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)').join(', ');
            const saved = await transaction.runAsync(
            `INSERT INTO coordinator_passengers
              (id, account_namespace, trip_id, display_name, employee_code, attendance_status,
               visa_status, flight_ticket_status, roster_version, updated_at)
             VALUES ${values}
             ON CONFLICT(account_namespace, trip_id, id) DO UPDATE SET
               display_name = excluded.display_name, employee_code = excluded.employee_code,
               attendance_status = excluded.attendance_status,
               visa_status = excluded.visa_status,
               flight_ticket_status = excluded.flight_ticket_status,
               roster_version = excluded.roster_version, updated_at = excluded.updated_at`,
            batch.flatMap((item) => [
              item.id,
              stage.namespace,
              stage.tripId,
              item.display_name,
              item.employee_code,
              'not_marked',
              item.visa_status,
              item.flight_ticket_status,
              descriptor.versions.roster,
              descriptor.server_time,
              ]),
            );
            if (saved.changes !== batch.length) {
              throw new Error('A manager roster row crossed its trip boundary.');
            }
          }
        },
        assertActive,
      );
  }

  assertActive?.();
  await transaction.runAsync(
    `DELETE FROM coordinator_passengers
      WHERE account_namespace = ? AND trip_id = ?
        AND NOT EXISTS (
          SELECT 1 FROM sync_rebase_staging staged
           WHERE staged.account_namespace = coordinator_passengers.account_namespace
             AND staged.trip_id = coordinator_passengers.trip_id
             AND staged.generation_id = ? AND staged.resource_type = 'roster'
             AND staged.item_key = coordinator_passengers.id
        )`,
    stage.namespace,
    stage.tripId,
    stage.generationId,
  );
}

async function replaceAttendanceSessions(
  transaction: SQLite.SQLiteDatabase,
  stage: SnapshotStageIdentity,
  descriptor: SyncSnapshot,
  assertActive?: ActiveAssertion,
): Promise<void> {
  if (descriptor.trip.role !== 'passenger') {
    await forEachStagedBatch(
      transaction,
      stage,
      'attendance_sessions',
      AttendanceSessionSchema,
      async (items) => {
        for (const batch of sqliteWriteBatches(items, 10)) {
          assertActive?.();
          const values = batch.map(() => '(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)').join(', ');
          const saved = await transaction.runAsync(
            `INSERT INTO attendance_sessions
              (id, account_namespace, trip_id, name, status, scanned_count, assigned_count,
               started_at, completed_at, updated_at)
             VALUES ${values}
             ON CONFLICT(id) DO UPDATE SET
               name = excluded.name, status = excluded.status,
               scanned_count = excluded.scanned_count,
               assigned_count = excluded.assigned_count,
               started_at = excluded.started_at, completed_at = excluded.completed_at,
               updated_at = excluded.updated_at
             WHERE attendance_sessions.account_namespace = excluded.account_namespace
               AND attendance_sessions.trip_id = excluded.trip_id`,
            batch.flatMap((session) => [
              session.id,
              stage.namespace,
              stage.tripId,
              session.name,
              session.status,
              session.scanned_count,
              session.assigned_count,
              session.started_at,
              session.completed_at,
              descriptor.server_time,
            ]),
          );
          if (saved.changes !== batch.length) {
            throw new Error('An attendance session crossed its trip boundary.');
          }
        }
      },
      assertActive,
    );
  }
  assertActive?.();
  await transaction.runAsync(
    `DELETE FROM attendance_sessions
      WHERE account_namespace = ? AND trip_id = ?
        AND NOT EXISTS (
          SELECT 1 FROM sync_rebase_staging staged
           WHERE staged.account_namespace = attendance_sessions.account_namespace
             AND staged.trip_id = attendance_sessions.trip_id
             AND staged.generation_id = ?
             AND staged.resource_type = 'attendance_sessions'
             AND staged.item_key = attendance_sessions.id
        )`,
    stage.namespace,
    stage.tripId,
    stage.generationId,
  );
  await transaction.runAsync(
    `DELETE FROM attendance_session_selection
      WHERE account_namespace = ? AND trip_id = ?
        AND session_id NOT IN (
          SELECT id FROM attendance_sessions
           WHERE account_namespace = ? AND trip_id = ?
             AND status IN ('draft', 'active')
        )`,
    stage.namespace,
    stage.tripId,
    stage.namespace,
    stage.tripId,
  );
  await transaction.runAsync(
    'DELETE FROM attendance_session_missing WHERE account_namespace = ? AND trip_id = ?',
    stage.namespace,
    stage.tripId,
  );
  await transaction.runAsync(
    'DELETE FROM attendance_summaries WHERE account_namespace = ? AND trip_id = ?',
    stage.namespace,
    stage.tripId,
  );
}

export async function promoteSnapshotStage(
  stage: SnapshotStageIdentity,
  descriptor: SyncSnapshot,
  syncContext: ImmutableSyncContext,
): Promise<void> {
  assertSyncContextActive(syncContext);
  const database = await openAccountDatabase(stage.namespace);
  assertSyncContextActive(syncContext);
  await withAccountTransaction(database, async (transaction) => {
    const assertActive = () => assertSyncContextActive(syncContext);
    assertActive();
    const tripState = await transaction.getFirstAsync<{
      access_generation: number;
      cursor: number | null;
    }>(
      `SELECT trip.access_generation, cursor.cursor
         FROM trips trip
         LEFT JOIN sync_cursors cursor
           ON cursor.account_namespace = trip.account_namespace AND cursor.trip_id = trip.id
        WHERE trip.account_namespace = ? AND trip.id = ?`,
      stage.namespace,
      stage.tripId,
    );
    if (!tripState || tripState.access_generation !== descriptor.access_generation) {
      throw new Error('Trip access changed before snapshot promotion.');
    }
    if (tripState.cursor !== null && tripState.cursor > descriptor.baseline_cursor) {
      throw new Error('The snapshot promotion would regress the durable cursor.');
    }

    const manifest = await stagedSingleton(
      transaction,
      stage,
      'manifest',
      ManifestSchema,
      assertActive,
    );
    if (
      !manifest
      || manifest.trip.id !== stage.tripId
      || manifest.trip.role !== descriptor.trip.role
      || manifest.trip.access_generation !== descriptor.access_generation
      || !snapshotVersionsEqual(manifest.versions, descriptor.versions)
    ) {
      throw new Error('The staged manifest did not match the committed snapshot fence.');
    }

    await replaceItinerary(transaction, stage, assertActive);
    await replaceAnnouncements(transaction, stage, assertActive);
    await replaceDocumentScope(
      transaction,
      stage,
      'common_documents',
      descriptor.server_time,
      assertActive,
    );
    if (descriptor.trip.role === 'passenger') {
      await replaceDocumentScope(
        transaction,
        stage,
        'personal_documents',
        descriptor.server_time,
        assertActive,
      );
    } else {
      await transaction.runAsync(
        `DELETE FROM document_metadata
          WHERE account_namespace = ? AND trip_id = ? AND scope = 'personal'`,
        stage.namespace,
        stage.tripId,
      );
    }
    await transaction.runAsync(
      `DELETE FROM offline_files
        WHERE account_namespace = ? AND trip_id = ?
          AND NOT EXISTS (
            SELECT 1 FROM document_metadata document
             WHERE document.id = offline_files.document_id
               AND document.account_namespace = offline_files.account_namespace
               AND document.trip_id = offline_files.trip_id
               AND document.revoked_at IS NULL
               AND document.version = offline_files.version
               AND lower(document.checksum_sha256) = lower(offline_files.checksum_sha256)
          )`,
      stage.namespace,
      stage.tripId,
    );
    await replacePassengerSingletons(transaction, stage, descriptor, assertActive);
    await replaceReadiness(transaction, stage, descriptor, assertActive);
    await replaceRoster(transaction, stage, descriptor, assertActive);
    await replaceAttendanceSessions(transaction, stage, descriptor, assertActive);
    assertActive();

    const applied = await transaction.runAsync(
      `UPDATE trips SET
         role = ?, name = ?, destination = ?, travel_date = ?, return_date = ?, timezone = ?,
         access_expires_at = ?,
         itinerary_version = ?, common_document_version = ?, personal_document_version = ?,
         announcement_version = ?, readiness_version = ?, roster_version = ?,
         rooming_version = ?, meals_version = ?, qr_version = ?,
         advertised_itinerary_version = ?, advertised_common_document_version = ?,
         advertised_personal_document_version = ?, advertised_announcement_version = ?,
         advertised_readiness_version = ?, advertised_roster_version = ?,
         advertised_rooming_version = ?, advertised_meals_version = ?, advertised_qr_version = ?,
         roster_projection_complete = ?,
         updated_at = ?
       WHERE account_namespace = ? AND id = ? AND access_generation = ?`,
      descriptor.trip.role,
      descriptor.trip.name,
      descriptor.trip.destination,
      descriptor.trip.travel_date,
      descriptor.trip.return_date,
      descriptor.trip.timezone,
      descriptor.access_expires_at,
      descriptor.versions.itinerary,
      descriptor.versions.common_documents,
      descriptor.versions.personal_documents,
      descriptor.versions.announcements,
      descriptor.versions.readiness,
      descriptor.versions.roster,
      descriptor.versions.rooming,
      descriptor.versions.meals,
      descriptor.versions.qr,
      descriptor.versions.itinerary,
      descriptor.versions.common_documents,
      descriptor.versions.personal_documents,
      descriptor.versions.announcements,
      descriptor.versions.readiness,
      descriptor.versions.roster,
      descriptor.versions.rooming,
      descriptor.versions.meals,
      descriptor.versions.qr,
      descriptor.trip.role === 'passenger' ? 0 : 1,
      descriptor.server_time,
      stage.namespace,
      stage.tripId,
      descriptor.access_generation,
    );
    if (applied.changes !== 1) throw new Error('Trip access changed during snapshot promotion.');
    await transaction.runAsync(
      `INSERT INTO sync_cursors
        (account_namespace, trip_id, cursor, access_generation, last_synced_at, last_error_code)
       VALUES (?, ?, ?, ?, ?, NULL)
       ON CONFLICT(account_namespace, trip_id) DO UPDATE SET
         cursor = excluded.cursor, access_generation = excluded.access_generation,
         last_synced_at = excluded.last_synced_at, last_error_code = NULL`,
      stage.namespace,
      stage.tripId,
      descriptor.baseline_cursor,
      descriptor.access_generation,
      descriptor.server_time,
    );
    await transaction.runAsync(
      `DELETE FROM sync_rebase_staging
        WHERE account_namespace = ? AND trip_id = ? AND generation_id = ?`,
      stage.namespace,
      stage.tripId,
      stage.generationId,
    );
    assertActive();
  });
}

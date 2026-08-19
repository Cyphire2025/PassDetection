import * as Crypto from 'expo-crypto';

import { ApiError, apiRequest } from '@/core/api/client';
import { principalAccountNamespace } from '@/core/auth/types';
import { useSessionStore } from '@/core/auth/session-store';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';
import {
  assertSyncContextActive,
  type ImmutableSyncContext,
} from '@/core/sync/sync-context';

import {
  AttendanceSummarySchema,
  CoordinatorPassengerDetailSchema,
  CoordinatorRosterSchema,
  type CoordinatorAttendanceTokenEvidence,
  type CoordinatorPassengerDetail,
} from '../api/coordinator-contracts';
import {
  collectAndReplaceRoster,
  MOBILE_GROUP_PASSENGER_CAPACITY,
} from './full-roster-sync';
import {
  isLocalRosterCursor,
  queryLocalRoster,
  type LocalRosterFilter,
} from './local-roster-search';
import { rosterWriteBatches } from './roster-write-batching';

type RosterItem = Awaited<ReturnType<typeof remoteRoster>>['items'][number];

type AttendanceTokenProjection = readonly [
  string | null,
  number | null,
  CoordinatorAttendanceTokenEvidence['state'] | 'unknown',
  string | null,
  string | null,
  string | null,
  string | null,
];

function attendanceTokenProjection(
  evidence: CoordinatorAttendanceTokenEvidence | null | undefined,
): AttendanceTokenProjection {
  if (!evidence) return [null, null, 'unknown', null, null, null, null];
  return [
    evidence.token_hash,
    evidence.token_version,
    evidence.state,
    evidence.token_expires_at,
    evidence.token_updated_at,
    evidence.evidence_observed_at,
    evidence.evidence_valid_until,
  ];
}

async function upsertRosterItems(
  transaction: Awaited<ReturnType<typeof openAccountDatabase>>,
  account: string,
  tripId: string,
  items: readonly RosterItem[],
  updatedAt: string,
  syncContext?: ImmutableSyncContext,
): Promise<void> {
  for (const batch of rosterWriteBatches(items)) {
    if (syncContext) assertSyncContextActive(syncContext);
    const values = batch.map(
      () => '(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)',
    ).join(', ');
    const parameters = batch.flatMap((item) => [
      item.id,
      account,
      tripId,
      item.display_name,
      item.employee_code,
      item.attendance_status,
      ...attendanceTokenProjection(item.attendance_token),
      item.room_number,
      item.meal_preference,
      item.has_alert ? 1 : 0,
      updatedAt,
    ]);
    await transaction.runAsync(
      `INSERT INTO coordinator_passengers
        (id, account_namespace, trip_id, display_name, employee_code, attendance_status,
         attendance_token_hash, attendance_token_version, attendance_token_state,
         attendance_token_expires_at, attendance_token_updated_at,
         attendance_evidence_observed_at, attendance_evidence_valid_until,
         room_number, meal_preference, has_alert, roster_version, updated_at)
       VALUES ${values}
       ON CONFLICT(account_namespace, trip_id, id) DO UPDATE SET
         display_name = excluded.display_name,
         employee_code = excluded.employee_code,
         attendance_status = excluded.attendance_status,
         attendance_token_hash = excluded.attendance_token_hash,
         attendance_token_version = excluded.attendance_token_version,
         attendance_token_state = excluded.attendance_token_state,
         attendance_token_expires_at = excluded.attendance_token_expires_at,
         attendance_token_updated_at = excluded.attendance_token_updated_at,
         attendance_evidence_observed_at = excluded.attendance_evidence_observed_at,
         attendance_evidence_valid_until = excluded.attendance_evidence_valid_until,
         room_number = excluded.room_number,
         meal_preference = excluded.meal_preference,
         has_alert = excluded.has_alert,
         roster_version = 0,
         updated_at = excluded.updated_at`,
      parameters,
    );
  }
}

function namespace(syncContext?: ImmutableSyncContext): string {
  if (syncContext) {
    assertSyncContextActive(syncContext);
    if (syncContext.role !== 'coordinator') throw new Error('Coordinator authentication is required.');
    return syncContext.namespace;
  }
  const principal = useSessionStore.getState().session?.principal;
  if (!principal || principal.principalType !== 'coordinator') throw new Error('Coordinator authentication is required.');
  return principalAccountNamespace(principal);
}

async function saveRoster(
  tripId: string,
  items: Awaited<ReturnType<typeof remoteRoster>>['items'],
  syncContext?: ImmutableSyncContext,
) {
  const account = namespace(syncContext);
  const database = await openAccountDatabase(account);
  if (syncContext) assertSyncContextActive(syncContext);
  const updatedAt = new Date().toISOString();
  await withAccountTransaction(database, async (transaction) => {
    await upsertRosterItems(transaction, account, tripId, items, updatedAt, syncContext);
  });
}

async function saveCoordinatorPassengerDetail(
  tripId: string,
  passenger: CoordinatorPassengerDetail,
  syncContext?: ImmutableSyncContext,
): Promise<void> {
  const account = namespace(syncContext);
  const database = await openAccountDatabase(account);
  if (syncContext) assertSyncContextActive(syncContext);
  const cachedAt = new Date().toISOString();
  const detailPayload = JSON.stringify(passenger);
  const attendanceToken = attendanceTokenProjection(passenger.attendance_token);
  await withAccountTransaction(database, async (transaction) => {
    if (syncContext) assertSyncContextActive(syncContext);
    await transaction.runAsync(
      `INSERT INTO coordinator_passengers
        (id, account_namespace, trip_id, display_name, employee_code, employee_type,
         attendance_status, phone_number, email, departure_city, nearest_domestic_airport,
         attendance_token_hash, attendance_token_version, attendance_token_state,
         attendance_token_expires_at, attendance_token_updated_at,
         attendance_evidence_observed_at, attendance_evidence_valid_until,
         designation, department, gender, date_of_birth, nationality, hotel_name, room_number,
         roommate_summary, meal_preference, family_relation, family_head_name, family_head_phone,
         family_head_email, passport_status, visa_status, flight_ticket_status, has_alert,
         detail_updated_at, detail_payload_json, detail_contract_version, roster_version, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
       ON CONFLICT(account_namespace, trip_id, id) DO UPDATE SET
         display_name = excluded.display_name,
         employee_code = excluded.employee_code,
         employee_type = excluded.employee_type,
         attendance_status = excluded.attendance_status,
         attendance_token_hash = excluded.attendance_token_hash,
         attendance_token_version = excluded.attendance_token_version,
         attendance_token_state = excluded.attendance_token_state,
         attendance_token_expires_at = excluded.attendance_token_expires_at,
         attendance_token_updated_at = excluded.attendance_token_updated_at,
         attendance_evidence_observed_at = excluded.attendance_evidence_observed_at,
         attendance_evidence_valid_until = excluded.attendance_evidence_valid_until,
         phone_number = excluded.phone_number,
         email = excluded.email,
         departure_city = excluded.departure_city,
         nearest_domestic_airport = excluded.nearest_domestic_airport,
         designation = excluded.designation,
         department = excluded.department,
         gender = excluded.gender,
         date_of_birth = excluded.date_of_birth,
         nationality = excluded.nationality,
         hotel_name = excluded.hotel_name,
         room_number = excluded.room_number,
         roommate_summary = excluded.roommate_summary,
         meal_preference = excluded.meal_preference,
         family_relation = excluded.family_relation,
         family_head_name = excluded.family_head_name,
         family_head_phone = excluded.family_head_phone,
         family_head_email = excluded.family_head_email,
         passport_status = excluded.passport_status,
         visa_status = excluded.visa_status,
         flight_ticket_status = excluded.flight_ticket_status,
         has_alert = excluded.has_alert,
         detail_updated_at = excluded.detail_updated_at,
         detail_payload_json = excluded.detail_payload_json,
         detail_contract_version = excluded.detail_contract_version,
         roster_version = 0,
         updated_at = excluded.updated_at`,
      passenger.id,
      account,
      tripId,
      passenger.display_name,
      passenger.employee_code,
      passenger.employee_type,
      passenger.attendance_status,
      passenger.phone_number,
      passenger.email,
      passenger.departure_city,
      passenger.nearest_domestic_airport,
      ...attendanceToken,
      passenger.designation,
      passenger.department,
      passenger.gender,
      passenger.date_of_birth,
      passenger.nationality,
      passenger.hotel_name,
      passenger.room_number,
      passenger.roommate_summary,
      passenger.meal_preference,
      passenger.family_relation,
      passenger.family_head_name,
      passenger.family_head_phone,
      passenger.family_head_email,
      passenger.passport_status,
      passenger.visa_status,
      passenger.flight_ticket_status,
      passenger.has_alert ? 1 : 0,
      passenger.updated_at,
      detailPayload,
      1,
      cachedAt,
    );
  });
}

export type CoordinatorPassengerChange = {
  passengerId: string;
  operation: 'upsert' | 'delete';
};

export async function applyCoordinatorPassengerChanges(
  tripId: string,
  changes: CoordinatorPassengerChange[],
  syncContext?: ImmutableSyncContext,
): Promise<void> {
  const account = namespace(syncContext);
  const database = await openAccountDatabase(account);
  if (syncContext) assertSyncContextActive(syncContext);
  const latest = new Map(changes.map((change) => [change.passengerId, change]));
  const bounded = [...latest.values()];
  for (let offset = 0; offset < bounded.length; offset += 6) {
    await Promise.all(
      bounded.slice(offset, offset + 6).map(async (change) => {
        if (change.operation === 'delete') {
          if (syncContext) assertSyncContextActive(syncContext);
          await database.runAsync(
            `DELETE FROM coordinator_passengers
              WHERE account_namespace = ? AND trip_id = ? AND id = ?`,
            account,
            tripId,
            change.passengerId,
          );
          return;
        }
        let passenger: CoordinatorPassengerDetail;
        try {
          passenger = await apiRequest(
            `/mobile/coordinator/groups/${tripId}/passengers/${change.passengerId}`,
            {
              schema: CoordinatorPassengerDetailSchema,
              ...(syncContext ? { signal: syncContext.signal } : {}),
            },
          );
        } catch (error) {
          if (!(error instanceof ApiError) || error.status !== 404) throw error;
          // The passenger may have become operationally ineligible after an
          // older upsert event was emitted. The scoped 404 is an authoritative
          // tombstone, not a transient failure.
          if (syncContext) assertSyncContextActive(syncContext);
          await database.runAsync(
            `DELETE FROM coordinator_passengers
              WHERE account_namespace = ? AND trip_id = ? AND id = ?`,
            account,
            tripId,
            change.passengerId,
          );
          return;
        }
        if (syncContext) assertSyncContextActive(syncContext);
        if (passenger.id !== change.passengerId) {
          throw new Error('Coordinator passenger synchronization was out of scope.');
        }
        await saveCoordinatorPassengerDetail(tripId, passenger, syncContext);
      }),
    );
  }
}

async function replaceRoster(
  tripId: string,
  items: Awaited<ReturnType<typeof remoteRoster>>['items'],
  syncContext?: ImmutableSyncContext,
) {
  const account = namespace(syncContext);
  const database = await openAccountDatabase(account);
  if (syncContext) assertSyncContextActive(syncContext);
  const updatedAt = new Date().toISOString();
  const generationId = Crypto.randomUUID();
  try {
    await withAccountTransaction(database, async (transaction) => {
      if (syncContext) assertSyncContextActive(syncContext);
      await transaction.runAsync(
        `DELETE FROM coordinator_roster_staging
          WHERE account_namespace = ? AND trip_id = ?`,
        account,
        tripId,
      );
    });

    let itemIndex = 0;
    for (const batch of rosterWriteBatches(items)) {
      if (syncContext) assertSyncContextActive(syncContext);
      await withAccountTransaction(database, async (transaction) => {
        if (syncContext) assertSyncContextActive(syncContext);
        const values = batch.map(
          () => '(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        ).join(', ');
        await transaction.runAsync(
          `INSERT INTO coordinator_roster_staging
            (account_namespace, trip_id, generation_id, item_index, id, display_name,
             employee_code, attendance_status, attendance_token_hash, attendance_token_version,
             attendance_token_state, attendance_token_expires_at, attendance_token_updated_at,
             attendance_evidence_observed_at, attendance_evidence_valid_until,
             room_number, meal_preference, has_alert, updated_at)
           VALUES ${values}`,
          batch.flatMap((item, offset) => [
            account,
            tripId,
            generationId,
            itemIndex + offset,
            item.id,
            item.display_name,
            item.employee_code,
            item.attendance_status,
            ...attendanceTokenProjection(item.attendance_token),
            item.room_number,
            item.meal_preference,
            item.has_alert ? 1 : 0,
            updatedAt,
          ]),
        );
      });
      itemIndex += batch.length;
    }

    if (syncContext) assertSyncContextActive(syncContext);
    await withAccountTransaction(database, async (transaction) => {
      if (syncContext) assertSyncContextActive(syncContext);
      const staged = await transaction.getFirstAsync<{
        item_count: number;
        maximum_index: number | null;
        minimum_index: number | null;
      }>(
        `SELECT COUNT(*) AS item_count, MIN(item_index) AS minimum_index,
                MAX(item_index) AS maximum_index
           FROM coordinator_roster_staging
          WHERE account_namespace = ? AND trip_id = ? AND generation_id = ?`,
        account,
        tripId,
        generationId,
      );
      if (
        staged?.item_count !== items.length
        || (items.length === 0
          ? staged.minimum_index !== null || staged.maximum_index !== null
          : staged.minimum_index !== 0 || staged.maximum_index !== items.length - 1)
      ) {
        throw new Error('The staged coordinator roster was incomplete.');
      }

      await transaction.runAsync(
        `UPDATE coordinator_passengers SET roster_version = -1
          WHERE account_namespace = ? AND trip_id = ?`,
        account,
        tripId,
      );
      const promoted = await transaction.runAsync(
        `INSERT INTO coordinator_passengers
          (id, account_namespace, trip_id, display_name, employee_code, attendance_status,
           attendance_token_hash, attendance_token_version, attendance_token_state,
           attendance_token_expires_at, attendance_token_updated_at,
           attendance_evidence_observed_at, attendance_evidence_valid_until,
           room_number, meal_preference, has_alert, roster_version, updated_at)
         SELECT id, account_namespace, trip_id, display_name, employee_code, attendance_status,
                attendance_token_hash, attendance_token_version, attendance_token_state,
                attendance_token_expires_at, attendance_token_updated_at,
                attendance_evidence_observed_at, attendance_evidence_valid_until,
                room_number, meal_preference, has_alert, 0, updated_at
           FROM coordinator_roster_staging
          WHERE account_namespace = ? AND trip_id = ? AND generation_id = ?
         ON CONFLICT(account_namespace, trip_id, id) DO UPDATE SET
           display_name = excluded.display_name,
           employee_code = excluded.employee_code,
           attendance_status = excluded.attendance_status,
           attendance_token_hash = excluded.attendance_token_hash,
           attendance_token_version = excluded.attendance_token_version,
           attendance_token_state = excluded.attendance_token_state,
           attendance_token_expires_at = excluded.attendance_token_expires_at,
           attendance_token_updated_at = excluded.attendance_token_updated_at,
           attendance_evidence_observed_at = excluded.attendance_evidence_observed_at,
           attendance_evidence_valid_until = excluded.attendance_evidence_valid_until,
           room_number = excluded.room_number,
           meal_preference = excluded.meal_preference,
           has_alert = excluded.has_alert,
           roster_version = 0,
           updated_at = excluded.updated_at`,
        account,
        tripId,
        generationId,
      );
      if (promoted.changes !== items.length) {
        throw new Error('The staged coordinator roster promotion was incomplete.');
      }
      await transaction.runAsync(
        `DELETE FROM coordinator_passengers
          WHERE account_namespace = ? AND trip_id = ? AND roster_version = -1`,
        account,
        tripId,
      );
      const marked = await transaction.runAsync(
        `UPDATE trips SET roster_projection_complete = 1
          WHERE account_namespace = ? AND id = ?`,
        account,
        tripId,
      );
      if (marked.changes !== 1) throw new Error('The coordinator roster crossed its trip boundary.');
      await transaction.runAsync(
        `DELETE FROM coordinator_roster_staging
          WHERE account_namespace = ? AND trip_id = ? AND generation_id = ?`,
        account,
        tripId,
        generationId,
      );
      if (syncContext) assertSyncContextActive(syncContext);
    });
  } catch (error) {
    await database.runAsync(
      `DELETE FROM coordinator_roster_staging
        WHERE account_namespace = ? AND trip_id = ? AND generation_id = ?`,
      account,
      tripId,
      generationId,
    ).catch(() => undefined);
    throw error;
  }
}

export async function loadCachedRoster(
  tripId: string,
  search: string,
  cursor: string | null = null,
  syncContext?: ImmutableSyncContext,
  filter: LocalRosterFilter = 'all',
) {
  const account = namespace(syncContext);
  const database = await openAccountDatabase(account);
  if (syncContext) assertSyncContextActive(syncContext);
  return queryLocalRoster({
    accountNamespace: account,
    ...(syncContext ? { assertActive: () => assertSyncContextActive(syncContext) } : {}),
    cursor,
    database,
    filter,
    search,
    tripId,
  });
}

function remoteRoster(
  tripId: string,
  search = '',
  cursor: string | null = null,
  syncContext?: ImmutableSyncContext,
  filter: LocalRosterFilter = 'all',
) {
  if (syncContext) assertSyncContextActive(syncContext);
  const query = new URLSearchParams({ filter, limit: '100' });
  if (search.trim()) query.set('search', search.trim());
  if (cursor) query.set('cursor', cursor);
  return apiRequest(`/mobile/coordinator/groups/${tripId}/passengers?${query.toString()}`, {
    schema: CoordinatorRosterSchema,
    ...(syncContext ? { signal: syncContext.signal } : {}),
  });
}

export async function loadRoster(
  tripId: string,
  search = '',
  cursor: string | null = null,
  syncContext?: ImmutableSyncContext,
  filter: LocalRosterFilter = 'all',
) {
  // Remote and local cursors intentionally occupy separate namespaces. Once
  // offline pagination starts, keep that traversal on the encrypted local
  // projection; a remote cursor cannot be safely translated to a local row.
  if (isLocalRosterCursor(cursor)) {
    return loadCachedRoster(tripId, search, cursor, syncContext, filter);
  }
  try {
    const result = await remoteRoster(tripId, search, cursor, syncContext, filter);
    if (syncContext) assertSyncContextActive(syncContext);
    await saveRoster(tripId, result.items, syncContext);
    return { ...result, offline: false };
  } catch (networkError) {
    if (syncContext) assertSyncContextActive(syncContext);
    if (cursor !== null) throw networkError;
    const local = await loadCachedRoster(tripId, search, cursor, syncContext, filter);
    if (local.items.length || local.projectionCompleteness.isComplete) return local;
    throw networkError;
  }
}

export async function loadCachedCoordinatorPassenger(
  tripId: string,
  passengerId: string,
  syncContext?: ImmutableSyncContext,
) {
  const account = namespace(syncContext);
  const database = await openAccountDatabase(account);
  if (syncContext) assertSyncContextActive(syncContext);
  const cached = await database.getFirstAsync<{
    detail_contract_version: number | null;
    detail_payload_json: string | null;
  }>(
    `SELECT detail_payload_json, detail_contract_version
       FROM coordinator_passengers
      WHERE account_namespace = ? AND trip_id = ? AND id = ? AND detail_updated_at IS NOT NULL
      LIMIT 1`,
    account,
    tripId,
    passengerId,
  );
  if (syncContext) assertSyncContextActive(syncContext);
  if (cached?.detail_contract_version === 1 && cached.detail_payload_json) {
    try {
      const parsed = CoordinatorPassengerDetailSchema.safeParse(
        JSON.parse(cached.detail_payload_json),
      );
      if (parsed.success && parsed.data.id === passengerId) return parsed.data;
    } catch {
      // A malformed or stale payload is ignored. The legacy normalized columns
      // below still provide a safe offline fallback until the next refresh.
    }
  }

  const passenger = await database.getFirstAsync<{
    attendance_status: CoordinatorPassengerDetail['attendance_status'];
    date_of_birth: string | null;
    department: string | null;
    departure_city: string | null;
    designation: string | null;
    display_name: string;
    email: string | null;
    employee_code: string | null;
    employee_type: string | null;
    family_head_email: string | null;
    family_head_name: string | null;
    family_head_phone: string | null;
    family_relation: string | null;
    flight_ticket_status: CoordinatorPassengerDetail['flight_ticket_status'];
    gender: string | null;
    has_alert: number;
    hotel_name: string | null;
    id: string;
    insurance_status?: CoordinatorPassengerDetail['insurance_status'];
    meal_preference: string | null;
    nationality: string | null;
    nearest_domestic_airport: string | null;
    passport_status: CoordinatorPassengerDetail['passport_status'];
    phone_number: string | null;
    room_number: string | null;
    roommate_summary: string | null;
    hotel_voucher_status?: CoordinatorPassengerDetail['hotel_voucher_status'];
    other_document_status?: CoordinatorPassengerDetail['other_document_status'];
    updated_at: string;
    visa_status: CoordinatorPassengerDetail['visa_status'];
  }>(
    `SELECT id, display_name, employee_code, employee_type, attendance_status, has_alert,
            phone_number, email, departure_city, nearest_domestic_airport, designation,
            department, gender, date_of_birth, nationality, hotel_name, room_number,
            roommate_summary, meal_preference, family_relation, family_head_name,
            family_head_phone, family_head_email, passport_status, visa_status,
            flight_ticket_status, detail_updated_at AS updated_at
       FROM coordinator_passengers
      WHERE account_namespace = ? AND trip_id = ? AND id = ? AND detail_updated_at IS NOT NULL
      LIMIT 1`,
    account,
    tripId,
    passengerId,
  );
  if (syncContext) assertSyncContextActive(syncContext);
  if (!passenger) return null;
  const parsed = CoordinatorPassengerDetailSchema.safeParse({
    ...passenger,
    additional_details: [],
    agency_dealership_name: null,
    base_city: null,
    emergency_contact_name: null,
    emergency_contact_phone: null,
    emergency_contact_relation: null,
    has_alert: Boolean(passenger.has_alert),
    hotel_voucher_status: passenger.hotel_voucher_status ?? 'not_available',
    insurance_status: passenger.insurance_status ?? 'not_available',
    operational_remarks: null,
    other_document_status: passenger.other_document_status ?? 'not_available',
    passport_date_of_expiry: null,
    passport_date_of_issue: null,
    passport_given_names: null,
    passport_issuing_country: null,
    passport_place_of_issue: null,
    passport_surname: null,
    qualifier_relation: null,
    staff_code: null,
    submission_mode: 'single',
    submission_status: 'unavailable',
    zone_name: null,
  });
  return parsed.success ? parsed.data : null;
}

export async function loadCoordinatorPassenger(
  tripId: string,
  passengerId: string,
  syncContext?: ImmutableSyncContext,
) {
  try {
    if (syncContext) assertSyncContextActive(syncContext);
    const passenger = await apiRequest(
      `/mobile/coordinator/groups/${tripId}/passengers/${passengerId}`,
      {
        schema: CoordinatorPassengerDetailSchema,
        ...(syncContext ? { signal: syncContext.signal } : {}),
      },
    );
    if (syncContext) assertSyncContextActive(syncContext);
    if (passenger.id !== passengerId) {
      throw new Error('Coordinator passenger details were out of scope.');
    }
    await saveCoordinatorPassengerDetail(tripId, passenger, syncContext);
    return { passenger, offline: false };
  } catch (networkError) {
    if (syncContext) assertSyncContextActive(syncContext);
    if (networkError instanceof ApiError && [401, 403, 404].includes(networkError.status)) {
      const account = namespace(syncContext);
      const database = await openAccountDatabase(account);
      if (syncContext) assertSyncContextActive(syncContext);
      await database.runAsync(
        'DELETE FROM coordinator_passengers WHERE account_namespace = ? AND trip_id = ? AND id = ?',
        account,
        tripId,
        passengerId,
      );
      if (syncContext) assertSyncContextActive(syncContext);
      throw networkError;
    }
    const passenger = await loadCachedCoordinatorPassenger(tripId, passengerId, syncContext);
    if (passenger) return { passenger, offline: true };
    throw networkError;
  }
}

export async function syncFullRoster(
  tripId: string,
  syncContext?: ImmutableSyncContext,
  expectedRosterRevision?: number,
) {
  if (syncContext) assertSyncContextActive(syncContext);
  let total = 0;
  let observedRosterRevision: number | null = null;
  const items = await collectAndReplaceRoster(
    async (cursor) => {
      if (syncContext) assertSyncContextActive(syncContext);
      const page = await remoteRoster(tripId, '', cursor, syncContext);
      if (syncContext) assertSyncContextActive(syncContext);
      if (
        page.roster_revision == null
        || (expectedRosterRevision !== undefined && page.roster_revision !== expectedRosterRevision)
        || (observedRosterRevision !== null && page.roster_revision !== observedRosterRevision)
      ) {
        throw new Error('The coordinator roster changed during synchronization.');
      }
      observedRosterRevision = page.roster_revision;
      total = page.total;
      return page;
    },
    (complete) => replaceRoster(tripId, complete, syncContext),
    MOBILE_GROUP_PASSENGER_CAPACITY,
    syncContext ? () => assertSyncContextActive(syncContext) : undefined,
  );
  if (syncContext) assertSyncContextActive(syncContext);
  return { items, next_cursor: null, total, offline: false };
}

export function loadAttendanceSummary(
  tripId: string,
  syncContext?: ImmutableSyncContext,
) {
  return refreshAttendanceSummary(tripId, syncContext);
}

async function localAttendanceSummary(
  tripId: string,
  syncContext?: ImmutableSyncContext,
) {
  const account = namespace(syncContext);
  const database = await openAccountDatabase(account);
  if (syncContext) assertSyncContextActive(syncContext);
  const row = await database.getFirstAsync<{
    total: number;
    present: number;
    missing: number;
    excused: number;
    not_marked: number;
    version: number;
    updated_at: string;
  }>(
    `SELECT total, present, missing, excused, not_marked, version, updated_at
       FROM attendance_summaries
      WHERE account_namespace = ? AND trip_id = ?`,
    account,
    tripId,
  );
  if (syncContext) assertSyncContextActive(syncContext);
  return row ? { trip_id: tripId, ...row } : null;
}

async function refreshAttendanceSummary(
  tripId: string,
  syncContext?: ImmutableSyncContext,
) {
  try {
    if (syncContext) assertSyncContextActive(syncContext);
    const summary = await apiRequest(`/mobile/coordinator/groups/${tripId}/attendance/summary`, {
      schema: AttendanceSummarySchema,
      ...(syncContext ? { signal: syncContext.signal } : {}),
    });
    if (syncContext) assertSyncContextActive(syncContext);
    const account = namespace(syncContext);
    const database = await openAccountDatabase(account);
    if (syncContext) assertSyncContextActive(syncContext);
    await database.runAsync(
      `INSERT INTO attendance_summaries
        (account_namespace, trip_id, total, present, missing, excused, not_marked, version, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(account_namespace, trip_id) DO UPDATE SET
         total = excluded.total,
         present = excluded.present,
         missing = excluded.missing,
         excused = excluded.excused,
         not_marked = excluded.not_marked,
         version = excluded.version,
         updated_at = excluded.updated_at`,
      account,
      tripId,
      summary.total,
      summary.present,
      summary.missing,
      summary.excused,
      summary.not_marked,
      summary.version,
      summary.updated_at,
    );
    return { summary, offline: false };
  } catch (networkError) {
    if (syncContext) assertSyncContextActive(syncContext);
    // A metadata synchronization must not mark a roster/attendance revision as
    // applied using an older cached summary. Cache fallback remains available
    // to ordinary UI reads that do not carry an immutable sync context.
    if (syncContext) throw networkError;
    const summary = await localAttendanceSummary(tripId, syncContext);
    if (summary) return { summary, offline: true };
    throw networkError;
  }
}

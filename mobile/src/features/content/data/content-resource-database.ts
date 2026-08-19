import type * as SQLite from 'expo-sqlite';

import type { Announcement } from '../api/content-contracts';

export type PersonalQrContent = Readonly<{
  id: string;
  trip_id: string;
  passenger_id: string;
  signed_payload: string;
  version: number;
  valid_from: string | null;
  valid_until: string | null;
  offline_allowed: boolean;
  updated_at: string;
}>;

export type RoomContent = Readonly<{
  id: string;
  trip_id: string;
  passenger_id: string | null;
  hotel_name: string | null;
  room_number: string | null;
  roommate_summary: string | null;
  version: number;
  updated_at: string;
}>;

export type MealContent = Readonly<{
  id: string;
  trip_id: string;
  passenger_id: string | null;
  preference: string | null;
  notes: string | null;
  version: number;
  updated_at: string;
}>;

export type ReadinessContent = Readonly<{
  trip_id: string;
  passenger_count: number;
  passports_complete: number;
  visas_available: number;
  tickets_available: number;
  items_needing_attention: number;
  rooms_assigned: number;
  meals_confirmed: number;
  version: number;
  updated_at: string;
}>;

export async function replaceAnnouncementsInTransaction(
  transaction: SQLite.SQLiteDatabase,
  options: Readonly<{
    namespace: string;
    tripId: string;
    announcements: readonly Announcement[];
    assertActive?: () => void;
  }>,
): Promise<void> {
  const { announcements, assertActive, namespace, tripId } = options;
  assertActive?.();
  const readIds = new Set(
    (
      await transaction.getAllAsync<{ id: string }>(
        'SELECT id FROM announcements WHERE account_namespace = ? AND trip_id = ? AND is_read = 1',
        namespace,
        tripId,
      )
    ).map((row) => row.id),
  );
  assertActive?.();
  await transaction.runAsync(
    'DELETE FROM announcements WHERE account_namespace = ? AND trip_id = ?',
    namespace,
    tripId,
  );
  for (const item of announcements) {
    assertActive?.();
    await transaction.runAsync(
      `INSERT INTO announcements
        (id, account_namespace, trip_id, version, title, message, priority, published_at, available_until, is_read)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      item.id,
      namespace,
      tripId,
      item.version,
      item.title,
      item.message,
      item.priority,
      item.published_at,
      item.available_until,
      item.is_read || readIds.has(item.id) ? 1 : 0,
    );
  }
}

export async function queryAnnouncements(
  database: SQLite.SQLiteDatabase,
  namespace: string,
  tripId: string,
): Promise<Announcement[]> {
  const rows = await database.getAllAsync<{
    id: string;
    version: number;
    title: string;
    message: string;
    priority: Announcement['priority'];
    published_at: string;
    available_until: string | null;
    is_read: number;
  }>(
    `SELECT id, version, title, message, priority, published_at, available_until, is_read
       FROM announcements
      WHERE account_namespace = ? AND trip_id = ?
      ORDER BY published_at DESC`,
    namespace,
    tripId,
  );
  return rows.map((row) => ({
    id: row.id,
    trip_id: tripId,
    version: row.version,
    title: row.title,
    message: row.message,
    priority: row.priority,
    published_at: row.published_at,
    available_until: row.available_until,
    is_read: Boolean(row.is_read),
  }));
}

export function markAnnouncementReadInDatabase(
  database: SQLite.SQLiteDatabase,
  namespace: string,
  announcementId: string,
): Promise<SQLite.SQLiteRunResult> {
  return database.runAsync(
    'UPDATE announcements SET is_read = 1 WHERE account_namespace = ? AND id = ?',
    namespace,
    announcementId,
  );
}

export function deletePersonalQr(
  database: SQLite.SQLiteDatabase,
  namespace: string,
  tripId: string,
): Promise<SQLite.SQLiteRunResult> {
  return database.runAsync(
    'DELETE FROM qr_metadata WHERE account_namespace = ? AND trip_id = ?',
    namespace,
    tripId,
  );
}

export function savePersonalQr(
  database: SQLite.SQLiteDatabase,
  namespace: string,
  tripId: string,
  qr: PersonalQrContent,
): Promise<SQLite.SQLiteRunResult> {
  return database.runAsync(
    `INSERT INTO qr_metadata
      (id, account_namespace, trip_id, passenger_id, signed_payload, version, valid_from,
       valid_until, offline_allowed, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(id) DO UPDATE SET
       signed_payload = excluded.signed_payload,
       version = excluded.version,
       valid_from = excluded.valid_from,
       valid_until = excluded.valid_until,
       offline_allowed = excluded.offline_allowed,
       updated_at = excluded.updated_at`,
    qr.id,
    namespace,
    tripId,
    qr.passenger_id,
    qr.signed_payload,
    qr.version,
    qr.valid_from,
    qr.valid_until,
    qr.offline_allowed ? 1 : 0,
    qr.updated_at,
  );
}

export async function queryPersonalQr(
  database: SQLite.SQLiteDatabase,
  namespace: string,
  tripId: string,
  nowIso: string,
): Promise<PersonalQrContent | null> {
  const row = await database.getFirstAsync<{
    id: string;
    passenger_id: string;
    signed_payload: string;
    version: number;
    valid_from: string | null;
    valid_until: string | null;
    offline_allowed: number;
    updated_at: string;
  }>(
    `SELECT id, passenger_id, signed_payload, version, valid_from, valid_until, offline_allowed, updated_at
       FROM qr_metadata WHERE account_namespace = ? AND trip_id = ? AND offline_allowed = 1
        AND (valid_from IS NULL OR valid_from <= ?)
        AND (valid_until IS NULL OR valid_until > ?)
       ORDER BY version DESC LIMIT 1`,
    namespace,
    tripId,
    nowIso,
    nowIso,
  );
  return row ? {
    id: row.id,
    trip_id: tripId,
    passenger_id: row.passenger_id,
    signed_payload: row.signed_payload,
    version: row.version,
    valid_from: row.valid_from,
    valid_until: row.valid_until,
    offline_allowed: Boolean(row.offline_allowed),
    updated_at: row.updated_at,
  } : null;
}

export function saveRoomAssignment(
  database: SQLite.SQLiteDatabase,
  namespace: string,
  tripId: string,
  room: RoomContent,
): Promise<SQLite.SQLiteRunResult> {
  return database.runAsync(
    `INSERT INTO room_assignments
      (id, account_namespace, trip_id, passenger_id, hotel_name, room_number, roommate_summary, version, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(id) DO UPDATE SET hotel_name = excluded.hotel_name, room_number = excluded.room_number,
       roommate_summary = excluded.roommate_summary, version = excluded.version, updated_at = excluded.updated_at`,
    room.id,
    namespace,
    tripId,
    room.passenger_id,
    room.hotel_name,
    room.room_number,
    room.roommate_summary,
    room.version,
    room.updated_at,
  );
}

export async function replaceRoomAssignmentInTransaction(
  database: SQLite.SQLiteDatabase,
  namespace: string,
  tripId: string,
  room: RoomContent,
): Promise<void> {
  await database.runAsync(
    'DELETE FROM room_assignments WHERE account_namespace = ? AND trip_id = ?',
    namespace,
    tripId,
  );
  await saveRoomAssignment(database, namespace, tripId, room);
}

export async function queryRoomAssignment(
  database: SQLite.SQLiteDatabase,
  namespace: string,
  tripId: string,
): Promise<(RoomContent & { offline: true }) | null> {
  const room = await database.getFirstAsync<Omit<RoomContent, 'trip_id'>>(
    'SELECT id, passenger_id, hotel_name, room_number, roommate_summary, version, updated_at FROM room_assignments WHERE account_namespace = ? AND trip_id = ? ORDER BY version DESC LIMIT 1',
    namespace,
    tripId,
  );
  return room ? { ...room, trip_id: tripId, offline: true } : null;
}

export function saveMealInformation(
  database: SQLite.SQLiteDatabase,
  namespace: string,
  tripId: string,
  meal: MealContent,
): Promise<SQLite.SQLiteRunResult> {
  return database.runAsync(
    `INSERT INTO meal_information
      (id, account_namespace, trip_id, passenger_id, preference, notes, version, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(id) DO UPDATE SET preference = excluded.preference, notes = excluded.notes,
       version = excluded.version, updated_at = excluded.updated_at`,
    meal.id,
    namespace,
    tripId,
    meal.passenger_id,
    meal.preference,
    meal.notes,
    meal.version,
    meal.updated_at,
  );
}

export async function replaceMealInformationInTransaction(
  database: SQLite.SQLiteDatabase,
  namespace: string,
  tripId: string,
  meal: MealContent,
): Promise<void> {
  await database.runAsync(
    'DELETE FROM meal_information WHERE account_namespace = ? AND trip_id = ?',
    namespace,
    tripId,
  );
  await saveMealInformation(database, namespace, tripId, meal);
}

export async function queryMealInformation(
  database: SQLite.SQLiteDatabase,
  namespace: string,
  tripId: string,
): Promise<(MealContent & { offline: true }) | null> {
  const meal = await database.getFirstAsync<Omit<MealContent, 'trip_id'>>(
    'SELECT id, passenger_id, preference, notes, version, updated_at FROM meal_information WHERE account_namespace = ? AND trip_id = ? ORDER BY version DESC LIMIT 1',
    namespace,
    tripId,
  );
  return meal ? { ...meal, trip_id: tripId, offline: true } : null;
}

export function saveReadiness(
  database: SQLite.SQLiteDatabase,
  namespace: string,
  tripId: string,
  readiness: ReadinessContent,
): Promise<SQLite.SQLiteRunResult> {
  return database.runAsync(
    `INSERT INTO manager_readiness
      (account_namespace, trip_id, passenger_count, passports_complete, visas_available, tickets_available,
       items_needing_attention, rooms_assigned, meals_confirmed, version, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(account_namespace, trip_id) DO UPDATE SET
       passenger_count = excluded.passenger_count, passports_complete = excluded.passports_complete,
       visas_available = excluded.visas_available, tickets_available = excluded.tickets_available,
       items_needing_attention = excluded.items_needing_attention, rooms_assigned = excluded.rooms_assigned,
       meals_confirmed = excluded.meals_confirmed, version = excluded.version, updated_at = excluded.updated_at`,
    namespace,
    tripId,
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

export async function queryReadiness(
  database: SQLite.SQLiteDatabase,
  namespace: string,
  tripId: string,
): Promise<(ReadinessContent & { offline: true }) | null> {
  const readiness = await database.getFirstAsync<Omit<ReadinessContent, 'trip_id'>>(
    'SELECT passenger_count, passports_complete, visas_available, tickets_available, items_needing_attention, rooms_assigned, meals_confirmed, version, updated_at FROM manager_readiness WHERE account_namespace = ? AND trip_id = ?',
    namespace,
    tripId,
  );
  return readiness ? { ...readiness, trip_id: tripId, offline: true } : null;
}

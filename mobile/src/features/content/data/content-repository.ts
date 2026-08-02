import { apiRequest, ApiError } from '@/core/api/client';
import { accountNamespace } from '@/core/auth/types';
import { useSessionStore } from '@/core/auth/session-store';
import { openAccountDatabase } from '@/core/storage/database';
import {
  deleteOfflineDocument,
  downloadAndEncryptDocument,
  removeAllOfflineDocuments,
} from '@/core/storage/vault';

import {
  AnnouncementListSchema,
  CommonDocumentListSchema,
  DocumentListSchema,
  MealSchema,
  PersonalQrSchema,
  ReadinessSchema,
  RoomSchema,
  type Announcement,
  type DocumentMetadata,
} from '../api/content-contracts';
import { collectCursorItems } from './cursor-pagination';

function activeNamespace(): string {
  const principal = useSessionStore.getState().session?.principal;
  if (!principal) throw new Error('Authentication is required.');
  return accountNamespace({ agencyId: principal.agencyId, principalId: principal.id });
}

async function saveAnnouncements(tripId: string, announcements: Announcement[]): Promise<void> {
  const namespace = activeNamespace();
  const database = await openAccountDatabase(namespace);
  await database.withTransactionAsync(async () => {
    const readIds = new Set(
      (
        await database.getAllAsync<{ id: string }>(
          'SELECT id FROM announcements WHERE account_namespace = ? AND trip_id = ? AND is_read = 1',
          namespace,
          tripId,
        )
      ).map((row) => row.id),
    );
    await database.runAsync(
      'DELETE FROM announcements WHERE account_namespace = ? AND trip_id = ?',
      namespace,
      tripId,
    );
    for (const item of announcements) {
      await database.runAsync(
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
  });
}

export async function localAnnouncements(tripId: string): Promise<Announcement[]> {
  const namespace = activeNamespace();
  const database = await openAccountDatabase(namespace);
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
      ORDER BY published_at DESC
      LIMIT 4000`,
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

export async function refreshAnnouncements(tripId: string) {
  try {
    const items = await collectCursorItems(
      (cursor) => apiRequest(
        `/mobile/trips/${tripId}/announcements?limit=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`,
        { schema: AnnouncementListSchema },
      ),
      { maxPages: 20, maxItems: 4_000 },
    );
    await saveAnnouncements(tripId, items);
    return { items, offline: false };
  } catch (networkError) {
    const items = await localAnnouncements(tripId);
    if (items.length) return { items, offline: true };
    throw networkError;
  }
}

export async function markAnnouncementRead(announcementId: string): Promise<void> {
  const namespace = activeNamespace();
  const database = await openAccountDatabase(namespace);
  await database.runAsync(
    'UPDATE announcements SET is_read = 1 WHERE account_namespace = ? AND id = ?',
    namespace,
    announcementId,
  );
}

async function saveDocuments(
  tripId: string,
  documents: DocumentMetadata[],
  scope: DocumentMetadata['scope'],
): Promise<void> {
  const namespace = activeNamespace();
  const database = await openAccountDatabase(namespace);
  const existing = await database.getAllAsync<{ id: string; version: number; checksum_sha256: string }>(
    `SELECT id, version, checksum_sha256 FROM document_metadata
      WHERE account_namespace = ? AND trip_id = ? AND scope = ?`,
    namespace,
    tripId,
    scope,
  );
  const current = new Map(documents.map((document) => [document.id, document]));
  for (const previous of existing) {
    const next = current.get(previous.id);
    if (
      !next ||
      next.revoked_at ||
      next.version !== previous.version ||
      !next.checksum_sha256 ||
      next.checksum_sha256.toLowerCase() !== previous.checksum_sha256.toLowerCase()
    ) {
      await deleteOfflineDocument(namespace, tripId, previous.id);
    }
  }
  await database.withTransactionAsync(async () => {
    const incomingIds = documents.map((document) => document.id);
    for (const document of documents) {
      await database.runAsync(
        `INSERT INTO document_metadata
          (id, account_namespace, trip_id, passenger_id, scope, category, display_name, content_type,
           size_bytes, version, checksum_sha256, offline_available, metadata_state, updated_at, revoked_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(id) DO UPDATE SET
           passenger_id = excluded.passenger_id,
           scope = excluded.scope,
           category = excluded.category,
           display_name = excluded.display_name,
           content_type = excluded.content_type,
           size_bytes = excluded.size_bytes,
           version = excluded.version,
           checksum_sha256 = excluded.checksum_sha256,
           offline_available = excluded.offline_available,
           metadata_state = excluded.metadata_state,
           updated_at = excluded.updated_at,
           revoked_at = excluded.revoked_at`,
        document.id,
        namespace,
        tripId,
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
      );
    }
    if (incomingIds.length) {
      const placeholders = incomingIds.map(() => '?').join(',');
      await database.runAsync(
        `DELETE FROM document_metadata
          WHERE account_namespace = ? AND trip_id = ? AND scope = ? AND id NOT IN (${placeholders})`,
        namespace,
        tripId,
        scope,
        ...incomingIds,
      );
    } else {
      await database.runAsync(
        'DELETE FROM document_metadata WHERE account_namespace = ? AND trip_id = ? AND scope = ?',
        namespace,
        tripId,
        scope,
      );
    }
  });
}

export type DocumentWithOfflineState = DocumentMetadata & {
  offline: boolean;
  offlineVersion: number | null;
};

export async function localDocuments(tripId: string): Promise<DocumentWithOfflineState[]> {
  const namespace = activeNamespace();
  const database = await openAccountDatabase(namespace);
  const rows = await database.getAllAsync<Omit<DocumentMetadata, 'size_bytes' | 'checksum_sha256' | 'offline_available'> & {
    size_bytes: number;
    checksum_sha256: string;
    offline_available: number;
    offline: number;
    offlineVersion: number | null;
  }>(
    `SELECT d.id, d.trip_id, d.passenger_id, d.scope, d.category, d.display_name, d.content_type,
            d.size_bytes, d.version, d.checksum_sha256, d.offline_available, d.metadata_state,
            d.updated_at, d.revoked_at,
            CASE WHEN f.document_id IS NULL THEN 0 ELSE 1 END AS offline,
            f.version AS offlineVersion
       FROM document_metadata d
      LEFT JOIN offline_files f ON f.document_id = d.id AND f.account_namespace = d.account_namespace
      WHERE d.account_namespace = ? AND d.trip_id = ? AND d.revoked_at IS NULL
      ORDER BY d.scope DESC, d.category, d.display_name
      LIMIT 4000`,
    namespace,
    tripId,
  );
  return rows.map((row) => ({
    ...row,
    size_bytes: row.metadata_state === 'ready' ? row.size_bytes : null,
    checksum_sha256: row.metadata_state === 'ready' ? row.checksum_sha256 : null,
    offline_available: Boolean(row.offline_available),
    offline: Boolean(row.offline),
    offlineVersion: row.offlineVersion,
  }));
}

export async function cacheDocument(document: DocumentMetadata): Promise<void> {
  if (
    document.metadata_state !== 'ready' ||
    !document.offline_available ||
    !document.size_bytes ||
    !document.checksum_sha256
  ) {
    throw new Error('This document is still being prepared for secure offline access.');
  }
  const namespace = activeNamespace();
  const database = await openAccountDatabase(namespace);
  const current = await database.getFirstAsync<{ version: number; checksum_sha256: string }>(
    `SELECT f.version, f.checksum_sha256
       FROM offline_files f
      WHERE f.account_namespace = ? AND f.document_id = ?`,
    namespace,
    document.id,
  );
  if (
    current?.version === document.version &&
    current.checksum_sha256.toLowerCase() === document.checksum_sha256.toLowerCase()
  ) {
    return;
  }

  const encrypted = await downloadAndEncryptDocument({
    namespace,
    tripId: document.trip_id,
    documentId: document.id,
    version: document.version,
    checksumSha256: document.checksum_sha256,
    expectedSizeBytes: document.size_bytes,
    contentType: document.content_type,
  });
  await database.runAsync(
    `INSERT INTO offline_files
      (document_id, account_namespace, trip_id, version, encrypted_path, checksum_sha256,
       encrypted_size_bytes, downloaded_at, last_opened_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
     ON CONFLICT(document_id) DO UPDATE SET
       version = excluded.version,
       encrypted_path = excluded.encrypted_path,
       checksum_sha256 = excluded.checksum_sha256,
       encrypted_size_bytes = excluded.encrypted_size_bytes,
       downloaded_at = excluded.downloaded_at,
       last_opened_at = NULL`,
    document.id,
    namespace,
    document.trip_id,
    document.version,
    encrypted.uri,
    encrypted.checksumSha256,
    encrypted.encryptedSizeBytes,
    new Date().toISOString(),
  );
}

export async function removeOfflineCache(): Promise<void> {
  const namespace = activeNamespace();
  const database = await openAccountDatabase(namespace);
  await removeAllOfflineDocuments(namespace);
  await database.runAsync('DELETE FROM offline_files WHERE account_namespace = ?', namespace);
}

export async function getDocument(documentId: string): Promise<DocumentWithOfflineState | null> {
  const namespace = activeNamespace();
  const database = await openAccountDatabase(namespace);
  const row = await database.getFirstAsync<Omit<DocumentMetadata, 'size_bytes' | 'checksum_sha256' | 'offline_available'> & {
    size_bytes: number;
    checksum_sha256: string;
    offline_available: number;
    offline: number;
    offlineVersion: number | null;
  }>(
    `SELECT d.id, d.trip_id, d.passenger_id, d.scope, d.category, d.display_name, d.content_type,
            d.size_bytes, d.version, d.checksum_sha256, d.offline_available, d.metadata_state,
            d.updated_at, d.revoked_at,
            CASE WHEN f.document_id IS NULL THEN 0 ELSE 1 END AS offline,
            f.version AS offlineVersion
       FROM document_metadata d
       LEFT JOIN offline_files f ON f.document_id = d.id AND f.account_namespace = d.account_namespace
      WHERE d.account_namespace = ? AND d.id = ? AND d.revoked_at IS NULL
      LIMIT 1`,
    namespace,
    documentId,
  );
  return row ? {
    ...row,
    size_bytes: row.metadata_state === 'ready' ? row.size_bytes : null,
    checksum_sha256: row.metadata_state === 'ready' ? row.checksum_sha256 : null,
    offline_available: Boolean(row.offline_available),
    offline: Boolean(row.offline),
    offlineVersion: row.offlineVersion,
  } : null;
}

export async function refreshDocuments(tripId: string) {
  try {
    const items = await collectCursorItems(
      (cursor) => apiRequest(
        `/mobile/trips/${tripId}/documents?limit=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`,
        { schema: DocumentListSchema },
      ),
      { maxPages: 20, maxItems: 4_000 },
    );
    await saveDocuments(tripId, items, 'personal');
    return { items: await localDocuments(tripId), offline: false };
  } catch (networkError) {
    const items = await localDocuments(tripId);
    if (items.length) return { items, offline: true };
    throw networkError;
  }
}

export async function refreshCommonDocuments(tripId: string) {
  try {
    const commonItems = await collectCursorItems(
      (cursor) => apiRequest(
        `/mobile/trips/${tripId}/common-documents?limit=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`,
        { schema: CommonDocumentListSchema },
      ),
      { maxPages: 20, maxItems: 4_000 },
    );
    const documents: DocumentMetadata[] = commonItems.map((item) => ({
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
    }));
    await saveDocuments(tripId, documents, 'common');
    return { items: (await localDocuments(tripId)).filter((item) => item.scope === 'common'), offline: false };
  } catch (networkError) {
    const items = (await localDocuments(tripId)).filter((item) => item.scope === 'common');
    if (items.length) return { items, offline: true };
    throw networkError;
  }
}

export async function refreshQr(tripId: string) {
  const namespace = activeNamespace();
  const database = await openAccountDatabase(namespace);
  let qr;
  try {
    qr = await apiRequest(`/mobile/trips/${tripId}/qr`, { schema: PersonalQrSchema });
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      await database.runAsync(
        'DELETE FROM qr_metadata WHERE account_namespace = ? AND trip_id = ?',
        namespace,
        tripId,
      );
    }
    throw error;
  }
  await database.runAsync(
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
  return { qr, offline: false };
}

export async function localQr(tripId: string) {
  const namespace = activeNamespace();
  const database = await openAccountDatabase(namespace);
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
    new Date().toISOString(),
    new Date().toISOString(),
  );
  if (!row) return null;
  return {
    id: row.id,
    trip_id: tripId,
    passenger_id: row.passenger_id,
    signed_payload: row.signed_payload,
    version: row.version,
    valid_from: row.valid_from,
    valid_until: row.valid_until,
    offline_allowed: Boolean(row.offline_allowed),
    updated_at: row.updated_at,
  };
}

export async function loadQr(tripId: string) {
  try {
    return await refreshQr(tripId);
  } catch (networkError) {
    const qr = await localQr(tripId);
    if (qr) return { qr, offline: true };
    throw networkError;
  }
}

export async function loadRoom(tripId: string) {
  const namespace = activeNamespace();
  const database = await openAccountDatabase(namespace);
  try {
    const room = await apiRequest(`/mobile/trips/${tripId}/room`, { schema: RoomSchema });
    await database.runAsync(
      `INSERT INTO room_assignments
        (id, account_namespace, trip_id, passenger_id, hotel_name, room_number, roommate_summary, version, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(id) DO UPDATE SET hotel_name = excluded.hotel_name, room_number = excluded.room_number,
         roommate_summary = excluded.roommate_summary, version = excluded.version, updated_at = excluded.updated_at`,
      room.id, namespace, tripId, room.passenger_id, room.hotel_name, room.room_number,
      room.roommate_summary, room.version, room.updated_at,
    );
    return { ...room, offline: false };
  } catch (networkError) {
    const room = await database.getFirstAsync<{
      id: string; passenger_id: string | null; hotel_name: string | null; room_number: string | null;
      roommate_summary: string | null; version: number; updated_at: string;
    }>('SELECT id, passenger_id, hotel_name, room_number, roommate_summary, version, updated_at FROM room_assignments WHERE account_namespace = ? AND trip_id = ? ORDER BY version DESC LIMIT 1', namespace, tripId);
    if (room) return { ...room, trip_id: tripId, offline: true };
    throw networkError;
  }
}

export async function loadMeal(tripId: string) {
  const namespace = activeNamespace();
  const database = await openAccountDatabase(namespace);
  try {
    const meal = await apiRequest(`/mobile/trips/${tripId}/meals`, { schema: MealSchema });
    await database.runAsync(
      `INSERT INTO meal_information
        (id, account_namespace, trip_id, passenger_id, preference, notes, version, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(id) DO UPDATE SET preference = excluded.preference, notes = excluded.notes,
         version = excluded.version, updated_at = excluded.updated_at`,
      meal.id, namespace, tripId, meal.passenger_id, meal.preference, meal.notes, meal.version, meal.updated_at,
    );
    return { ...meal, offline: false };
  } catch (networkError) {
    const meal = await database.getFirstAsync<{
      id: string; passenger_id: string | null; preference: string | null; notes: string | null;
      version: number; updated_at: string;
    }>('SELECT id, passenger_id, preference, notes, version, updated_at FROM meal_information WHERE account_namespace = ? AND trip_id = ? ORDER BY version DESC LIMIT 1', namespace, tripId);
    if (meal) return { ...meal, trip_id: tripId, offline: true };
    throw networkError;
  }
}

export async function loadReadiness(tripId: string) {
  const namespace = activeNamespace();
  const database = await openAccountDatabase(namespace);
  try {
    const readiness = await apiRequest(`/mobile/manager/groups/${tripId}/readiness`, { schema: ReadinessSchema });
    await database.runAsync(
      `INSERT INTO manager_readiness
        (account_namespace, trip_id, passenger_count, passports_complete, visas_available, tickets_available,
         items_needing_attention, rooms_assigned, meals_confirmed, version, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(account_namespace, trip_id) DO UPDATE SET
         passenger_count = excluded.passenger_count, passports_complete = excluded.passports_complete,
         visas_available = excluded.visas_available, tickets_available = excluded.tickets_available,
         items_needing_attention = excluded.items_needing_attention, rooms_assigned = excluded.rooms_assigned,
         meals_confirmed = excluded.meals_confirmed, version = excluded.version, updated_at = excluded.updated_at`,
      namespace, tripId, readiness.passenger_count, readiness.passports_complete, readiness.visas_available,
      readiness.tickets_available, readiness.items_needing_attention, readiness.rooms_assigned,
      readiness.meals_confirmed, readiness.version, readiness.updated_at,
    );
    return { ...readiness, offline: false };
  } catch (networkError) {
    const readiness = await database.getFirstAsync<{
      passenger_count: number; passports_complete: number; visas_available: number; tickets_available: number;
      items_needing_attention: number; rooms_assigned: number; meals_confirmed: number; version: number; updated_at: string;
    }>('SELECT passenger_count, passports_complete, visas_available, tickets_available, items_needing_attention, rooms_assigned, meals_confirmed, version, updated_at FROM manager_readiness WHERE account_namespace = ? AND trip_id = ?', namespace, tripId);
    if (readiness) return { ...readiness, trip_id: tripId, offline: true };
    throw networkError;
  }
}

import type * as SQLite from 'expo-sqlite';

import type { VaultResumeCandidate } from '@/core/storage/vault';

import type { DocumentMetadata } from '../api/content-contracts';
import { shouldPrefetchPassengerDocument } from './passenger-document-policy';

export type DocumentWithOfflineState = DocumentMetadata & {
  offline: boolean;
  offlineVersion: number | null;
};

export type RetryableOfflineDocument = DocumentWithOfflineState & {
  retryAttemptCount: number;
};

export type DocumentOwnershipFilter = Readonly<{
  sql: string;
  parameters: readonly string[];
}>;

type DocumentRow = Omit<
  DocumentMetadata,
  'size_bytes' | 'checksum_sha256' | 'offline_available'
> & {
  size_bytes: number;
  checksum_sha256: string;
  offline_available: number;
  offline: number;
  offlineVersion: number | null;
};

type RetryableDocumentRow = DocumentRow & {
  retryAttemptCount: number;
};

type DocumentLookupRow = DocumentRow & {
  access_expires_at: string | null;
  last_server_time: string | null;
};

export type DocumentLookup = Readonly<{
  document: DocumentWithOfflineState;
  accessExpiresAt: string | null;
  lastServerTime: string | null;
}>;

export type StoredDocumentForCache = Readonly<{
  id: string;
  account_namespace: string;
  trip_id: string;
  scope: DocumentMetadata['scope'];
  category: string;
  content_type: string;
  size_bytes: number;
  version: number;
  checksum_sha256: string;
  offline_available: number;
  metadata_state: DocumentMetadata['metadata_state'];
}>;

export type OfflineDocumentRegistration = Readonly<{
  version: number;
  checksum_sha256: string;
  encrypted_path: string;
}>;

export type TripVaultState = Readonly<{
  registeredUris: readonly string[];
  resumableDocuments: readonly VaultResumeCandidate[];
}>;

export function mapDocumentRow(row: DocumentRow): DocumentWithOfflineState {
  return {
    ...row,
    size_bytes: row.metadata_state === 'ready' ? row.size_bytes : null,
    checksum_sha256: row.metadata_state === 'ready' ? row.checksum_sha256 : null,
    offline_available: Boolean(row.offline_available),
    offline: Boolean(row.offline),
    offlineVersion: row.offlineVersion,
  };
}

export async function queryTripVaultState(
  database: SQLite.SQLiteDatabase,
  namespace: string,
  tripId: string,
): Promise<TripVaultState> {
  const rows = await database.getAllAsync<{
    encrypted_path: string | null;
    document_id: string | null;
    version: number | null;
    checksum_sha256: string | null;
  }>(
    `SELECT encrypted_path, NULL AS document_id, NULL AS version, NULL AS checksum_sha256
       FROM offline_files
      WHERE account_namespace = ? AND trip_id = ?
      UNION ALL
     SELECT NULL AS encrypted_path, d.id AS document_id, d.version, d.checksum_sha256
       FROM offline_document_jobs job
       JOIN document_metadata d
         ON d.id = job.document_id
        AND d.account_namespace = job.account_namespace
        AND d.trip_id = job.trip_id
        AND d.version = job.version
      WHERE job.account_namespace = ? AND job.trip_id = ?
        AND job.state IN ('pending', 'retryable')
        AND d.revoked_at IS NULL
        AND d.metadata_state = 'ready'
        AND d.offline_available = 1`,
    namespace,
    tripId,
    namespace,
    tripId,
  );
  return {
    registeredUris: rows
      .map((row) => row.encrypted_path)
      .filter((uri): uri is string => typeof uri === 'string'),
    resumableDocuments: rows
      .filter((row): row is typeof row & {
        document_id: string;
        version: number;
        checksum_sha256: string;
      } => (
        typeof row.document_id === 'string'
        && typeof row.version === 'number'
        && typeof row.checksum_sha256 === 'string'
      ))
      .map((row) => ({
        documentId: row.document_id,
        version: row.version,
        checksumSha256: row.checksum_sha256,
      })),
  };
}

export async function replaceDocumentsInTransaction(
  transaction: SQLite.SQLiteDatabase,
  options: Readonly<{
    namespace: string;
    tripId: string;
    scope: DocumentMetadata['scope'];
    documents: readonly DocumentMetadata[];
    assertActive?: () => void;
    nowIso: string;
  }>,
): Promise<void> {
  const { assertActive, documents, namespace, nowIso, scope, tripId } = options;
  const incomingIds = documents.map((document) => document.id);
  for (const document of documents) {
    assertActive?.();
    await transaction.runAsync(
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
    if (shouldPrefetchPassengerDocument(document)) {
      await transaction.runAsync(
        `INSERT INTO offline_document_jobs
          (document_id, account_namespace, trip_id, version, state, attempt_count,
           next_attempt_at, last_error_code, created_at, updated_at)
         VALUES (?, ?, ?, ?, 'pending', 0, NULL, NULL, ?, ?)
         ON CONFLICT(document_id) DO UPDATE SET
           account_namespace = excluded.account_namespace,
           trip_id = excluded.trip_id,
           version = excluded.version,
           state = CASE
             WHEN offline_document_jobs.version <> excluded.version THEN 'pending'
             ELSE offline_document_jobs.state
           END,
           attempt_count = CASE
             WHEN offline_document_jobs.version <> excluded.version THEN 0
             ELSE offline_document_jobs.attempt_count
           END,
           next_attempt_at = CASE
             WHEN offline_document_jobs.version <> excluded.version THEN NULL
             ELSE offline_document_jobs.next_attempt_at
           END,
           last_error_code = CASE
             WHEN offline_document_jobs.version <> excluded.version THEN NULL
             ELSE offline_document_jobs.last_error_code
           END,
           updated_at = excluded.updated_at`,
        document.id,
        namespace,
        tripId,
        document.version,
        nowIso,
        nowIso,
      );
    } else {
      await transaction.runAsync(
        `DELETE FROM offline_document_jobs
          WHERE document_id = ? AND account_namespace = ? AND trip_id = ?`,
        document.id,
        namespace,
        tripId,
      );
    }
  }
  assertActive?.();
  if (incomingIds.length) {
    const placeholders = incomingIds.map(() => '?').join(',');
    await transaction.runAsync(
      `DELETE FROM document_metadata
        WHERE account_namespace = ? AND trip_id = ? AND scope = ? AND id NOT IN (${placeholders})`,
      namespace,
      tripId,
      scope,
      ...incomingIds,
    );
  } else {
    await transaction.runAsync(
      'DELETE FROM document_metadata WHERE account_namespace = ? AND trip_id = ? AND scope = ?',
      namespace,
      tripId,
      scope,
    );
  }
  await transaction.runAsync(
    `DELETE FROM offline_files
      WHERE account_namespace = ?
        AND trip_id = ?
        AND NOT EXISTS (
          SELECT 1
            FROM document_metadata d
           WHERE d.id = offline_files.document_id
             AND d.account_namespace = offline_files.account_namespace
             AND d.trip_id = offline_files.trip_id
             AND d.revoked_at IS NULL
             AND d.version = offline_files.version
             AND lower(d.checksum_sha256) = lower(offline_files.checksum_sha256)
        )`,
    namespace,
    tripId,
  );
  assertActive?.();
}

export async function queryLocalDocuments(
  database: SQLite.SQLiteDatabase,
  options: Readonly<{
    namespace: string;
    tripId: string;
    ownership: DocumentOwnershipFilter;
    scope?: DocumentMetadata['scope'];
  }>,
): Promise<DocumentWithOfflineState[]> {
  const { namespace, ownership, scope, tripId } = options;
  const rows = await database.getAllAsync<DocumentRow>(
    `SELECT d.id, d.trip_id, d.passenger_id, d.scope, d.category, d.display_name, d.content_type,
            d.size_bytes, d.version, d.checksum_sha256, d.offline_available, d.metadata_state,
            d.updated_at, d.revoked_at,
            CASE WHEN f.document_id IS NULL THEN 0 ELSE 1 END AS offline,
            f.version AS offlineVersion
       FROM document_metadata d
      LEFT JOIN offline_files f ON f.document_id = d.id AND f.account_namespace = d.account_namespace
      WHERE d.account_namespace = ? AND d.trip_id = ? AND d.revoked_at IS NULL
        ${ownership.sql}
        ${scope ? 'AND d.scope = ?' : ''}
      ORDER BY d.scope DESC, d.category, d.display_name
      LIMIT 4000`,
    namespace,
    tripId,
    ...ownership.parameters,
    ...(scope ? [scope] : []),
  );
  return rows.map(mapDocumentRow);
}

export async function queryRetryableOfflineDocuments(
  database: SQLite.SQLiteDatabase,
  options: Readonly<{
    namespace: string;
    tripId: string;
    scopes: readonly DocumentMetadata['scope'][];
    ownership: DocumentOwnershipFilter;
    includeDeferred: boolean;
    nowIso: string;
  }>,
): Promise<RetryableOfflineDocument[]> {
  const { includeDeferred, namespace, nowIso, ownership, scopes, tripId } = options;
  if (!scopes.length) return [];
  const placeholders = scopes.map(() => '?').join(',');
  const rows = await database.getAllAsync<RetryableDocumentRow>(
    `SELECT d.id, d.trip_id, d.passenger_id, d.scope, d.category, d.display_name, d.content_type,
            d.size_bytes, d.version, d.checksum_sha256, d.offline_available, d.metadata_state,
            d.updated_at, d.revoked_at,
            CASE WHEN f.document_id IS NULL THEN 0 ELSE 1 END AS offline,
            f.version AS offlineVersion,
            job.attempt_count AS retryAttemptCount
       FROM offline_document_jobs job
       JOIN document_metadata d
         ON d.id = job.document_id
        AND d.account_namespace = job.account_namespace
        AND d.trip_id = job.trip_id
        AND d.version = job.version
       LEFT JOIN offline_files f
         ON f.document_id = d.id
        AND f.account_namespace = d.account_namespace
        AND f.trip_id = d.trip_id
      WHERE job.account_namespace = ? AND job.trip_id = ?
        AND job.state IN ('pending', 'retryable')
        AND (? = 1 OR job.next_attempt_at IS NULL OR job.next_attempt_at <= ?)
        AND d.scope IN (${placeholders})
        ${ownership.sql}
        AND d.revoked_at IS NULL
      ORDER BY COALESCE(job.next_attempt_at, job.created_at), d.display_name
      LIMIT 4000`,
    namespace,
    tripId,
    includeDeferred ? 1 : 0,
    nowIso,
    ...scopes,
    ...ownership.parameters,
  );
  return rows.map((row) => ({
    ...mapDocumentRow(row),
    retryAttemptCount: row.retryAttemptCount,
  }));
}

export async function queryDocument(
  database: SQLite.SQLiteDatabase,
  options: Readonly<{
    namespace: string;
    tripId: string;
    documentId: string;
    ownership: DocumentOwnershipFilter;
  }>,
): Promise<DocumentLookup | null> {
  const { documentId, namespace, ownership, tripId } = options;
  const row = await database.getFirstAsync<DocumentLookupRow>(
    `SELECT d.id, d.trip_id, d.passenger_id, d.scope, d.category, d.display_name, d.content_type,
            d.size_bytes, d.version, d.checksum_sha256, d.offline_available, d.metadata_state,
            d.updated_at, d.revoked_at,
            trip.access_expires_at,
            (SELECT MAX(cursor.last_synced_at)
               FROM sync_cursors cursor
              WHERE cursor.account_namespace = d.account_namespace
                AND cursor.trip_id = d.trip_id) AS last_server_time,
            CASE WHEN f.document_id IS NULL THEN 0 ELSE 1 END AS offline,
            f.version AS offlineVersion
       FROM document_metadata d
       JOIN trips trip ON trip.id = d.trip_id AND trip.account_namespace = d.account_namespace
       LEFT JOIN offline_files f ON f.document_id = d.id
        AND f.account_namespace = d.account_namespace
        AND f.trip_id = d.trip_id
      WHERE d.account_namespace = ?
        AND d.trip_id = ?
        ${ownership.sql}
        AND d.id = ?
        AND d.revoked_at IS NULL
      LIMIT 1`,
    namespace,
    tripId,
    ...ownership.parameters,
    documentId,
  );
  if (!row) return null;
  const {
    access_expires_at: accessExpiresAt,
    last_server_time: lastServerTime,
    ...documentRow
  } = row;
  return {
    document: mapDocumentRow(documentRow),
    accessExpiresAt,
    lastServerTime,
  };
}

export function queryStoredDocumentForCache(
  database: SQLite.SQLiteDatabase,
  namespace: string,
  tripId: string,
  documentId: string,
  version: number,
): Promise<StoredDocumentForCache | null> {
  return database.getFirstAsync<StoredDocumentForCache>(
    `SELECT id, account_namespace, trip_id, scope, category, content_type, size_bytes, version,
            checksum_sha256, offline_available, metadata_state
       FROM document_metadata
      WHERE account_namespace = ? AND trip_id = ? AND id = ? AND version = ? AND revoked_at IS NULL
        AND NOT EXISTS (
          SELECT 1 FROM trip_purge_tombstones purge
           WHERE purge.account_namespace = document_metadata.account_namespace
             AND purge.trip_id = document_metadata.trip_id
        )
      LIMIT 1`,
    namespace,
    tripId,
    documentId,
    version,
  );
}

export function queryOfflineDocumentRegistration(
  database: SQLite.SQLiteDatabase,
  namespace: string,
  tripId: string,
  documentId: string,
): Promise<OfflineDocumentRegistration | null> {
  return database.getFirstAsync<OfflineDocumentRegistration>(
    `SELECT f.version, f.checksum_sha256, f.encrypted_path
       FROM offline_files f
      WHERE f.account_namespace = ? AND f.trip_id = ? AND f.document_id = ?`,
    namespace,
    tripId,
    documentId,
  );
}

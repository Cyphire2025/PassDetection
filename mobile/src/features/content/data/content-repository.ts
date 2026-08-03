import { apiRequest, ApiError } from '@/core/api/client';
import { principalAccountNamespace } from '@/core/auth/types';
import { useSessionStore } from '@/core/auth/session-store';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';
import {
  assertSyncContextActive,
  isSyncContextChanged,
  type ImmutableSyncContext,
} from '@/core/sync/sync-context';
import { isAccessLeaseExpired } from '@/core/sync/access-expiry-policy';
import {
  discardEncryptedOfflineFile,
  downloadAndEncryptDocument,
  finalizeEncryptedOfflineFile,
  inspectRegisteredOfflineFile,
  isLocalOfflineCiphertextError,
  LocalOfflineCiphertextError,
  reconcileTripVault,
  removeRegisteredOfflineFile,
  type EncryptedOfflineFile,
  type VaultResumeCandidate,
} from '@/core/storage/vault';
import { offlinePrefetchConcurrency } from '@/core/storage/vault-policy';

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
import {
  documentRetryAction,
  documentRetryDelayMs,
  isDocumentMetadataConflict,
  isRetryableDocumentError,
  MAX_DOCUMENT_DOWNLOAD_ATTEMPTS,
} from './document-retry-policy';
import { shouldPrefetchPassengerDocument } from './passenger-document-policy';

const documentDownloads = new Map<string, Promise<void>>();
const recoveredTripVaults = new Set<string>();
const vaultRecoveryJobs = new Map<string, Promise<void>>();
const MAX_DURABLE_DOCUMENT_RETRY_DELAY_MS = 6 * 60 * 60 * 1_000;

type AccountDatabase = Awaited<ReturnType<typeof openAccountDatabase>>;

async function reconcileRegisteredTripVault(
  database: AccountDatabase,
  namespace: string,
  tripId: string,
): Promise<void> {
  // Query first and let any database failure abort cleanup. The vault validates every selected
  // path before deleting anything, so corrupt or cross-namespace state always fails closed.
  const vaultState = await database.getAllAsync<{
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
  const registeredUris = vaultState
    .map((row) => row.encrypted_path)
    .filter((uri): uri is string => typeof uri === 'string');
  const resumableDocuments = vaultState
    .filter((row): row is typeof row & {
      document_id: string;
      version: number;
      checksum_sha256: string;
    } => (
      typeof row.document_id === 'string'
      && typeof row.version === 'number'
      && typeof row.checksum_sha256 === 'string'
    ))
    .map<VaultResumeCandidate>((row) => ({
      documentId: row.document_id,
      version: row.version,
      checksumSha256: row.checksum_sha256,
    }));
  if (resumableDocuments.length) {
    await reconcileTripVault(namespace, tripId, registeredUris, resumableDocuments);
  } else {
    await reconcileTripVault(namespace, tripId, registeredUris);
  }
  recoveredTripVaults.add(`${namespace}:${tripId}`);
}

async function recoverTripVaultOnce(
  database: AccountDatabase,
  namespace: string,
  tripId: string,
): Promise<void> {
  const key = `${namespace}:${tripId}`;
  if (recoveredTripVaults.has(key)) return;
  const current = vaultRecoveryJobs.get(key);
  if (current) return current;
  const recovery = reconcileRegisteredTripVault(database, namespace, tripId)
    .finally(() => {
      if (vaultRecoveryJobs.get(key) === recovery) vaultRecoveryJobs.delete(key);
    });
  vaultRecoveryJobs.set(key, recovery);
  await recovery;
}

function documentAbortError(signal?: AbortSignal): Error {
  if (signal?.reason instanceof Error) return signal.reason;
  const error = new Error('Document operation was cancelled.');
  error.name = 'AbortError';
  return error;
}

function assertDocumentOperationActive(signal?: AbortSignal): void {
  if (signal?.aborted) throw documentAbortError(signal);
}

function wait(milliseconds: number, signal?: AbortSignal): Promise<void> {
  assertDocumentOperationActive(signal);
  if (!signal) return new Promise((resolve) => setTimeout(resolve, milliseconds));
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (operation: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal.removeEventListener('abort', onAbort);
      operation();
    };
    const onAbort = () => finish(() => reject(documentAbortError(signal)));
    const timer = setTimeout(() => finish(resolve), milliseconds);
    signal.addEventListener('abort', onAbort, { once: true });
    if (signal.aborted) onAbort();
  });
}

async function awaitWithSignal<T>(promise: Promise<T>, signal?: AbortSignal): Promise<T> {
  assertDocumentOperationActive(signal);
  if (!signal) return promise;
  return new Promise<T>((resolve, reject) => {
    let settled = false;
    const finish = (operation: () => void) => {
      if (settled) return;
      settled = true;
      signal.removeEventListener('abort', onAbort);
      operation();
    };
    const onAbort = () => finish(() => reject(documentAbortError(signal)));
    signal.addEventListener('abort', onAbort, { once: true });
    if (signal.aborted) onAbort();
    void promise.then(
      (value) => finish(() => resolve(value)),
      (error: unknown) => finish(() => reject(error)),
    );
  });
}

function activeNamespace(syncContext?: ImmutableSyncContext): string {
  if (syncContext) {
    assertSyncContextActive(syncContext);
    return syncContext.namespace;
  }
  const principal = useSessionStore.getState().session?.principal;
  if (!principal) throw new Error('Authentication is required.');
  return principalAccountNamespace(principal);
}

async function saveAnnouncements(
  tripId: string,
  announcements: Announcement[],
  syncContext?: ImmutableSyncContext,
): Promise<void> {
  const namespace = activeNamespace(syncContext);
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  await withAccountTransaction(database, async (transaction) => {
    if (syncContext) assertSyncContextActive(syncContext);
    const readIds = new Set(
      (
        await transaction.getAllAsync<{ id: string }>(
          'SELECT id FROM announcements WHERE account_namespace = ? AND trip_id = ? AND is_read = 1',
          namespace,
          tripId,
        )
      ).map((row) => row.id),
    );
    if (syncContext) assertSyncContextActive(syncContext);
    await transaction.runAsync(
      'DELETE FROM announcements WHERE account_namespace = ? AND trip_id = ?',
      namespace,
      tripId,
    );
    for (const item of announcements) {
      if (syncContext) assertSyncContextActive(syncContext);
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
  });
}

export async function localAnnouncements(
  tripId: string,
  syncContext?: ImmutableSyncContext,
): Promise<Announcement[]> {
  const namespace = activeNamespace(syncContext);
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
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

export async function refreshAnnouncements(tripId: string, syncContext?: ImmutableSyncContext) {
  try {
    if (syncContext) assertSyncContextActive(syncContext);
    const items = await collectCursorItems(
      (cursor) => {
        if (syncContext) assertSyncContextActive(syncContext);
        return apiRequest(
          `/mobile/trips/${tripId}/announcements?limit=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`,
          {
            schema: AnnouncementListSchema,
            ...(syncContext ? { signal: syncContext.signal } : {}),
          },
        );
      },
      { maxPages: 20, maxItems: 4_000 },
    );
    if (syncContext) assertSyncContextActive(syncContext);
    await saveAnnouncements(tripId, items, syncContext);
    return { items, offline: false };
  } catch (networkError) {
    if (syncContext) assertSyncContextActive(syncContext);
    const items = await localAnnouncements(tripId, syncContext);
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
  syncContext?: ImmutableSyncContext,
): Promise<void> {
  const namespace = activeNamespace(syncContext);
  const principal = useSessionStore.getState().session?.principal;
  if (!principal) throw new Error('Authentication is required.');
  const passengerId = principal.principalType === 'passenger' ? principal.passengerId : null;
  if (scope === 'personal' && (!passengerId || principal.principalType !== 'passenger')) {
    throw new Error('The passenger ownership boundary is unavailable. Sign in again while online.');
  }
  if (documents.some((document) => (
    document.trip_id !== tripId
    || document.scope !== scope
    || (scope === 'personal' && document.passenger_id !== passengerId)
    || (scope === 'common' && document.passenger_id !== null)
  ))) {
    throw new Error('The document response crossed its authorized trip or passenger boundary.');
  }
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  await withAccountTransaction(database, async (transaction) => {
    const incomingIds = documents.map((document) => document.id);
    const jobUpdatedAt = new Date().toISOString();
    for (const document of documents) {
      if (syncContext) assertSyncContextActive(syncContext);
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
          jobUpdatedAt,
          jobUpdatedAt,
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
    if (syncContext) assertSyncContextActive(syncContext);
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
    // Revoke a stale registration in the same SQLite commit as its metadata replacement.
    // Physical ciphertext remains untouched until the transaction has committed successfully.
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
    // Do not mark the durable job complete merely because an SQLite
    // registration exists. The prefetch worker verifies that the ciphertext is
    // still present before deleting the job, repairing OS/file loss safely.
    if (syncContext) assertSyncContextActive(syncContext);
  });
  if (syncContext) assertSyncContextActive(syncContext);
  await reconcileRegisteredTripVault(database, namespace, tripId);
}

export type DocumentWithOfflineState = DocumentMetadata & {
  offline: boolean;
  offlineVersion: number | null;
};

export async function localDocuments(
  tripId: string,
  syncContext?: ImmutableSyncContext,
  scope?: DocumentMetadata['scope'],
): Promise<DocumentWithOfflineState[]> {
  const namespace = activeNamespace(syncContext);
  const principal = useSessionStore.getState().session?.principal;
  if (!principal) throw new Error('Authentication is required.');
  const passengerId = principal.principalType === 'passenger' ? principal.passengerId : null;
  if (scope === 'personal' && (!passengerId || principal.principalType !== 'passenger')) return [];
  const ownershipClause = principal.principalType === 'passenger'
    ? "AND (d.scope = 'common' OR (d.scope = 'personal' AND d.passenger_id = ?))"
    : "AND d.scope = 'common'";
  const ownershipParameters = principal.principalType === 'passenger' ? [passengerId!] : [];
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  await recoverTripVaultOnce(database, namespace, tripId);
  if (syncContext) assertSyncContextActive(syncContext);
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
        ${ownershipClause}
        ${scope ? 'AND d.scope = ?' : ''}
      ORDER BY d.scope DESC, d.category, d.display_name
      LIMIT 4000`,
    namespace,
    tripId,
    ...ownershipParameters,
    ...(scope ? [scope] : []),
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

export async function cacheDocument(
  document: DocumentMetadata,
  syncContext?: ImmutableSyncContext,
  signal?: AbortSignal,
): Promise<void> {
  const operationSignal = signal ?? syncContext?.signal;
  assertDocumentOperationActive(operationSignal);
  const principal = useSessionStore.getState().session?.principal;
  if (!principal) throw new Error('Authentication is required.');
  if (
    document.scope === 'personal'
    && (principal.principalType !== 'passenger'
      || !principal.passengerId
      || document.passenger_id !== principal.passengerId)
  ) {
    throw new Error('The personal document does not belong to the active passenger.');
  }
  const namespace = activeNamespace(syncContext);
  // Serialize every version of one logical document. Different version keys could otherwise
  // race their SQLite registration and cleanup, leaving the older request as the winner.
  const downloadKey = `${namespace}:${document.trip_id}:${document.id}`;
  const inFlight = documentDownloads.get(downloadKey);
  if (inFlight) {
    try {
      await awaitWithSignal(inFlight, operationSignal);
    } catch (error) {
      if (
        !operationSignal?.aborted
        && error instanceof Error
        && error.name === 'AbortError'
      ) {
        // The previous owner may have closed its viewer. Its cancellation must not poison a live
        // background worker or a second viewer that joined the same logical document operation.
        return cacheDocument(document, syncContext, signal);
      }
      throw error;
    }
    if (syncContext) assertSyncContextActive(syncContext);
    assertDocumentOperationActive(operationSignal);
    return cacheDocument(document, syncContext, signal);
  }

  const download = cacheDocumentForNamespace(
    namespace,
    document,
    syncContext,
    operationSignal,
  ).finally(() => {
    if (documentDownloads.get(downloadKey) === download) documentDownloads.delete(downloadKey);
  });
  documentDownloads.set(downloadKey, download);
  await awaitWithSignal(download, operationSignal);
  if (syncContext) assertSyncContextActive(syncContext);
  assertDocumentOperationActive(operationSignal);
}

async function cacheDocumentForNamespace(
  namespace: string,
  document: DocumentMetadata,
  syncContext?: ImmutableSyncContext,
  signal?: AbortSignal,
): Promise<void> {
  assertDocumentOperationActive(signal);
  if (syncContext) assertSyncContextActive(syncContext);
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  const stored = await database.getFirstAsync<{
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
  }>(
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
    document.trip_id,
    document.id,
    document.version,
  );
  if (!stored) throw new Error('This document is no longer available for the selected trip.');

  const pendingPersonalDocument = stored.metadata_state === 'pending' && shouldPrefetchPassengerDocument({
    ...document,
    scope: stored.scope,
    category: stored.category,
    metadata_state: stored.metadata_state,
    offline_available: Boolean(stored.offline_available),
    size_bytes: null,
    checksum_sha256: null,
  });
  const readyDocument = (
    stored.metadata_state === 'ready' &&
    Boolean(stored.offline_available) &&
    stored.size_bytes > 0 &&
    /^[0-9a-f]{64}$/i.test(stored.checksum_sha256)
  );
  if (!pendingPersonalDocument && !readyDocument) {
    throw new Error('This document is still being prepared for secure offline access.');
  }

  const current = await database.getFirstAsync<{
    version: number;
    checksum_sha256: string;
    encrypted_path: string;
  }>(
    `SELECT f.version, f.checksum_sha256, f.encrypted_path
       FROM offline_files f
      WHERE f.account_namespace = ? AND f.trip_id = ? AND f.document_id = ?`,
    namespace,
    stored.trip_id,
    document.id,
  );
  let preserveRegisteredUri: string | null | undefined = current?.encrypted_path;
  if (
    readyDocument &&
    current?.version === document.version &&
    current.checksum_sha256.toLowerCase() === stored.checksum_sha256.toLowerCase()
  ) {
    const registeredInput = {
      namespace,
      tripId: stored.trip_id,
      documentId: document.id,
      version: document.version,
      checksumSha256: stored.checksum_sha256,
      expectedSizeBytes: stored.size_bytes,
      contentType: stored.content_type,
      encryptedUri: current.encrypted_path,
    };
    const inspection = await inspectRegisteredOfflineFile(registeredInput, signal);
    if (inspection.status === 'valid') {
      await database.runAsync(
        `DELETE FROM offline_document_jobs
          WHERE document_id = ? AND account_namespace = ? AND trip_id = ? AND version = ?`,
        document.id,
        namespace,
        stored.trip_id,
        document.version,
      );
      return;
    }

    // Make the damaged copy unreachable before any network operation. The durable job survives an
    // offline failure/restart and will resume repair later; orphan cleanup handles a crash between
    // this commit and physical deletion.
    const repairQueuedAt = new Date().toISOString();
    await withAccountTransaction(database, async (transaction) => {
      await transaction.runAsync(
        `DELETE FROM offline_files
          WHERE document_id = ? AND account_namespace = ? AND trip_id = ? AND version = ?
            AND lower(checksum_sha256) = lower(?) AND encrypted_path = ?`,
        document.id,
        namespace,
        stored.trip_id,
        document.version,
        stored.checksum_sha256,
        current.encrypted_path,
      );
      await transaction.runAsync(
        `INSERT INTO offline_document_jobs
          (document_id, account_namespace, trip_id, version, state, attempt_count,
           next_attempt_at, last_error_code, created_at, updated_at)
         VALUES (?, ?, ?, ?, 'pending', 0, NULL, ?, ?, ?)
         ON CONFLICT(document_id) DO UPDATE SET
           account_namespace = excluded.account_namespace,
           trip_id = excluded.trip_id,
           version = excluded.version,
           state = 'pending',
           next_attempt_at = NULL,
           last_error_code = excluded.last_error_code,
           updated_at = excluded.updated_at`,
        document.id,
        namespace,
        stored.trip_id,
        document.version,
        inspection.status === 'corrupt'
          ? 'LOCAL_CIPHERTEXT_CORRUPT'
          : 'LOCAL_CIPHERTEXT_MISSING',
        repairQueuedAt,
        repairQueuedAt,
      );
    });
    preserveRegisteredUri = null;
    if (inspection.status === 'corrupt') {
      await removeRegisteredOfflineFile(registeredInput);
    }
  }

  let encrypted: EncryptedOfflineFile | null = null;
  try {
    assertDocumentOperationActive(signal);
    const downloaded = await downloadAndEncryptDocument({
      namespace,
      tripId: stored.trip_id,
      documentId: document.id,
      version: document.version,
      ...(readyDocument ? {
        checksumSha256: stored.checksum_sha256,
        expectedSizeBytes: stored.size_bytes,
        contentType: stored.content_type,
      } : {}),
    }, signal);
    encrypted = downloaded;
    if (syncContext) assertSyncContextActive(syncContext);
    assertDocumentOperationActive(signal);
    const candidateInspection = await inspectRegisteredOfflineFile({
      namespace,
      tripId: stored.trip_id,
      documentId: document.id,
      version: document.version,
      checksumSha256: downloaded.checksumSha256,
      expectedSizeBytes: downloaded.plaintextSizeBytes,
      contentType: downloaded.contentType,
      encryptedUri: downloaded.uri,
    }, signal);
    if (candidateInspection.status !== 'valid') {
      throw new LocalOfflineCiphertextError(
        'The newly saved encrypted document copy failed local integrity verification.',
      );
    }
    await withAccountTransaction(database, async (transaction) => {
      if (syncContext) assertSyncContextActive(syncContext);
      const updated = await transaction.runAsync(
        `UPDATE document_metadata
            SET content_type = ?, size_bytes = ?, checksum_sha256 = ?, offline_available = 1,
                metadata_state = 'ready'
          WHERE account_namespace = ? AND trip_id = ? AND id = ? AND version = ? AND revoked_at IS NULL`,
        downloaded.contentType,
        downloaded.plaintextSizeBytes,
        downloaded.checksumSha256,
        namespace,
        stored.trip_id,
        document.id,
        document.version,
      );
      if (updated.changes !== 1) {
        throw new Error('Document access changed while the encrypted copy was being saved.');
      }
      if (syncContext) assertSyncContextActive(syncContext);
      await transaction.runAsync(
        `INSERT INTO offline_files
          (document_id, account_namespace, trip_id, version, encrypted_path, checksum_sha256,
           encrypted_size_bytes, downloaded_at, last_opened_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
         ON CONFLICT(document_id) DO UPDATE SET
           account_namespace = excluded.account_namespace,
           trip_id = excluded.trip_id,
           version = excluded.version,
           encrypted_path = excluded.encrypted_path,
           checksum_sha256 = excluded.checksum_sha256,
           encrypted_size_bytes = excluded.encrypted_size_bytes,
           downloaded_at = excluded.downloaded_at,
           last_opened_at = NULL`,
        document.id,
        namespace,
        stored.trip_id,
        document.version,
        downloaded.uri,
        downloaded.checksumSha256,
        downloaded.encryptedSizeBytes,
        new Date().toISOString(),
      );
      await transaction.runAsync(
        `DELETE FROM offline_document_jobs
          WHERE document_id = ? AND account_namespace = ? AND trip_id = ? AND version = ?`,
        document.id,
        namespace,
        stored.trip_id,
        document.version,
      );
      if (syncContext) assertSyncContextActive(syncContext);
    });
  } catch (error) {
    if (encrypted) {
      // A failed/rolled-back registration discards only this candidate. A previously registered
      // version remains intact and continues to serve offline until a replacement commits.
      discardEncryptedOfflineFile(encrypted, preserveRegisteredUri);
    }
    if (syncContext && isSyncContextChanged(error)) assertSyncContextActive(syncContext);
    throw error;
  }
  finalizeEncryptedOfflineFile(encrypted);
  if (syncContext) assertSyncContextActive(syncContext);
  await reconcileRegisteredTripVault(database, namespace, stored.trip_id);
}

export type OfflinePrefetchProgress = {
  total: number;
  completed: number;
  failed: number;
  currentDocumentName: string | null;
};

type RetryableOfflineDocument = DocumentWithOfflineState & {
  retryAttemptCount: number;
};

export function durableDocumentRetryDelayMs(
  failedAttempt: number,
  random: () => number = Math.random,
): number {
  const exponent = Math.max(0, Math.min(10, failedAttempt - 1));
  const base = Math.min(MAX_DURABLE_DOCUMENT_RETRY_DELAY_MS, 30_000 * (2 ** exponent));
  const jitter = Math.floor(Math.max(0, Math.min(1, random())) * Math.min(5_000, base / 4));
  return base + jitter;
}

function safeDocumentFailure(error: unknown): Readonly<{
  code: string;
  retryable: boolean;
}> {
  if (isLocalOfflineCiphertextError(error)) {
    return { code: 'LOCAL_CIPHERTEXT_CORRUPT', retryable: true };
  }
  if (isDocumentMetadataConflict(error)) return { code: 'DOCUMENT_METADATA_CONFLICT', retryable: true };
  if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
    return { code: 'DOCUMENT_ACCESS_DENIED', retryable: false };
  }
  if (error instanceof ApiError && error.status === 429) {
    return { code: 'DOCUMENT_RATE_LIMITED', retryable: true };
  }
  if (error instanceof ApiError && error.status >= 500) {
    return { code: 'DOCUMENT_PROVIDER_UNAVAILABLE', retryable: true };
  }
  const errorCode = typeof error === 'object' && error !== null && 'code' in error
    && typeof error.code === 'string'
    ? error.code
    : '';
  if (
    /CHECKSUM|INTEGRITY|CONTENT_TYPE|CONTENT_LENGTH|CONTENT_RANGE/.test(errorCode)
    || (error instanceof Error && (
      error.name === 'DocumentTransferIntegrityError'
      || /checksum|integrity|content (?:type|length|range)/i.test(error.message)
    ))
  ) {
    return { code: 'DOCUMENT_INTEGRITY_FAILED', retryable: false };
  }
  if (isRetryableDocumentError(error)) return { code: 'DOCUMENT_TRANSFER_RETRY', retryable: true };
  return { code: 'DOCUMENT_SAVE_FAILED', retryable: true };
}

async function retryableOfflineDocuments(
  tripId: string,
  scopes: ReadonlySet<DocumentMetadata['scope']>,
  syncContext?: ImmutableSyncContext,
  includeDeferred = false,
): Promise<RetryableOfflineDocument[]> {
  const namespace = activeNamespace(syncContext);
  const principal = useSessionStore.getState().session?.principal;
  if (!principal) throw new Error('Authentication is required.');
  const passengerId = principal.principalType === 'passenger' ? principal.passengerId : null;
  if (scopes.has('personal') && (!passengerId || principal.principalType !== 'passenger')) {
    throw new Error('The passenger ownership boundary is unavailable. Sign in again while online.');
  }
  const ownershipClause = principal.principalType === 'passenger'
    ? "AND (d.scope = 'common' OR (d.scope = 'personal' AND d.passenger_id = ?))"
    : "AND d.scope = 'common'";
  const ownershipParameters = principal.principalType === 'passenger' ? [passengerId!] : [];
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  const scopeValues = [...scopes];
  if (!scopeValues.length) return [];
  const placeholders = scopeValues.map(() => '?').join(',');
  const now = new Date().toISOString();
  const rows = await database.getAllAsync<{
    id: string;
    trip_id: string;
    passenger_id: string | null;
    scope: DocumentMetadata['scope'];
    category: string;
    display_name: string;
    content_type: DocumentMetadata['content_type'];
    size_bytes: number;
    version: number;
    checksum_sha256: string;
    offline_available: number;
    metadata_state: DocumentMetadata['metadata_state'];
    updated_at: string;
    revoked_at: string | null;
    offline: number;
    offlineVersion: number | null;
    retryAttemptCount: number;
  }>(
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
        ${ownershipClause}
        AND d.revoked_at IS NULL
      ORDER BY COALESCE(job.next_attempt_at, job.created_at), d.display_name
      LIMIT 4000`,
    namespace,
    tripId,
    includeDeferred ? 1 : 0,
    now,
    ...scopeValues,
    ...ownershipParameters,
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

async function recordOfflineDocumentFailure(
  document: RetryableOfflineDocument,
  error: unknown,
  syncContext?: ImmutableSyncContext,
): Promise<void> {
  const namespace = activeNamespace(syncContext);
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  const failure = safeDocumentFailure(error);
  const nextAttempt = failure.retryable
    ? new Date(Date.now() + durableDocumentRetryDelayMs(document.retryAttemptCount + 1)).toISOString()
    : null;
  await database.runAsync(
    `UPDATE offline_document_jobs
        SET state = ?, attempt_count = attempt_count + 1, next_attempt_at = ?,
            last_error_code = ?, updated_at = ?
      WHERE document_id = ? AND account_namespace = ? AND trip_id = ? AND version = ?`,
    failure.retryable ? 'retryable' : 'blocked',
    nextAttempt,
    failure.code,
    new Date().toISOString(),
    document.id,
    namespace,
    document.trip_id,
    document.version,
  );
}

async function cacheDocumentWithRetry(
  document: DocumentMetadata,
  syncContext?: ImmutableSyncContext,
): Promise<void> {
  const signal = syncContext?.signal;
  let candidate = document;
  let refreshedAfterConflict = false;
  for (let attempt = 1; attempt <= MAX_DOCUMENT_DOWNLOAD_ATTEMPTS; attempt += 1) {
    try {
      if (syncContext) assertSyncContextActive(syncContext);
      await cacheDocument(candidate, syncContext, signal);
      return;
    } catch (error) {
      if (syncContext) assertSyncContextActive(syncContext);
      const action = documentRetryAction(error, attempt, refreshedAfterConflict);
      if (action === 'refresh_metadata') {
        refreshedAfterConflict = true;
        const refreshed = candidate.scope === 'common'
          ? await refreshCommonDocuments(candidate.trip_id, syncContext)
          : await refreshDocuments(candidate.trip_id, syncContext);
        const replacement = refreshed.items.find((item) => item.id === candidate.id && !item.revoked_at);
        if (!replacement) throw new Error('This document is no longer available for the selected trip.');
        candidate = replacement;
        await wait(documentRetryDelayMs(attempt), signal);
        continue;
      }
      if (action === 'fail') throw error;
      await wait(documentRetryDelayMs(attempt), signal);
    }
  }
}

async function prefetchOfflineDocuments(
  tripId: string,
  scopes: ReadonlySet<DocumentMetadata['scope']>,
  onProgress?: (progress: OfflinePrefetchProgress) => void,
  syncContext?: ImmutableSyncContext,
  includeDeferred = false,
): Promise<OfflinePrefetchProgress> {
  if (syncContext) assertSyncContextActive(syncContext);
  const documents = await retryableOfflineDocuments(
    tripId,
    scopes,
    syncContext,
    includeDeferred,
  );
  const progress: OfflinePrefetchProgress = {
    total: documents.length,
    completed: 0,
    failed: 0,
    currentDocumentName: null,
  };
  onProgress?.({ ...progress });
  if (!documents.length) return progress;

  let nextIndex = 0;
  const worker = async () => {
    while (nextIndex < documents.length) {
      if (syncContext) assertSyncContextActive(syncContext);
      const index = nextIndex;
      nextIndex += 1;
      const document = documents[index];
      if (!document) continue;
      progress.currentDocumentName = document.display_name;
      onProgress?.({ ...progress });
      try {
        await cacheDocumentWithRetry(document, syncContext);
        progress.completed += 1;
      } catch (error) {
        if (syncContext) assertSyncContextActive(syncContext);
        await recordOfflineDocumentFailure(document, error, syncContext);
        progress.failed += 1;
      }
      onProgress?.({ ...progress });
    }
  };

  const concurrency = offlinePrefetchConcurrency(documents.map((document) => document.size_bytes));
  await Promise.all(Array.from({ length: concurrency }, () => worker()));
  progress.currentDocumentName = null;
  onProgress?.({ ...progress });
  return progress;
}

const PASSENGER_DOCUMENT_SCOPES = new Set<DocumentMetadata['scope']>(['personal', 'common']);
const COMMON_DOCUMENT_SCOPE = new Set<DocumentMetadata['scope']>(['common']);

export function prefetchPassengerOfflineDocuments(
  tripId: string,
  onProgress?: (progress: OfflinePrefetchProgress) => void,
  syncContext?: ImmutableSyncContext,
): Promise<OfflinePrefetchProgress> {
  return prefetchOfflineDocuments(tripId, PASSENGER_DOCUMENT_SCOPES, onProgress, syncContext);
}

export function prefetchCommonOfflineDocuments(
  tripId: string,
  onProgress?: (progress: OfflinePrefetchProgress) => void,
  syncContext?: ImmutableSyncContext,
): Promise<OfflinePrefetchProgress> {
  return prefetchOfflineDocuments(tripId, COMMON_DOCUMENT_SCOPE, onProgress, syncContext);
}

/** A foreground launch is an explicit retry boundary for required offline files. */
export function prefetchRequiredPassengerOfflineDocuments(
  tripId: string,
  onProgress?: (progress: OfflinePrefetchProgress) => void,
  syncContext?: ImmutableSyncContext,
): Promise<OfflinePrefetchProgress> {
  return prefetchOfflineDocuments(
    tripId,
    PASSENGER_DOCUMENT_SCOPES,
    onProgress,
    syncContext,
    true,
  );
}

export function prefetchRequiredCommonOfflineDocuments(
  tripId: string,
  onProgress?: (progress: OfflinePrefetchProgress) => void,
  syncContext?: ImmutableSyncContext,
): Promise<OfflinePrefetchProgress> {
  return prefetchOfflineDocuments(
    tripId,
    COMMON_DOCUMENT_SCOPE,
    onProgress,
    syncContext,
    true,
  );
}

export async function countMissingRequiredOfflineDocuments(
  tripId: string,
  scopes: ReadonlySet<DocumentMetadata['scope']>,
  syncContext?: ImmutableSyncContext,
): Promise<number> {
  const documents = await localDocuments(tripId, syncContext);
  return documents.filter((document) => (
    scopes.has(document.scope)
    && shouldPrefetchPassengerDocument(document)
    && (!document.offline || document.offlineVersion !== document.version)
  )).length;
}

export const REQUIRED_PASSENGER_DOCUMENT_SCOPES: ReadonlySet<DocumentMetadata['scope']> =
  PASSENGER_DOCUMENT_SCOPES;
export const REQUIRED_COMMON_DOCUMENT_SCOPES: ReadonlySet<DocumentMetadata['scope']> =
  COMMON_DOCUMENT_SCOPE;

export async function getDocument(
  tripId: string,
  documentId: string,
): Promise<DocumentWithOfflineState | null> {
  const principal = useSessionStore.getState().session?.principal;
  if (!principal) throw new Error('Authentication is required.');
  const namespace = principalAccountNamespace(principal);
  const database = await openAccountDatabase(namespace);
  const passengerId = principal.principalType === 'passenger' ? principal.passengerId : null;
  if (principal.principalType === 'passenger' && !passengerId) {
    throw new Error('The passenger ownership boundary is unavailable. Sign in again while online.');
  }
  const scopeClause = principal.principalType === 'passenger'
    ? "(d.scope = 'common' OR (d.scope = 'personal' AND d.passenger_id = ?))"
    : "d.scope = 'common'";
  const ownershipParameters = principal.principalType === 'passenger'
    ? [passengerId!]
    : [];
  const row = await database.getFirstAsync<Omit<DocumentMetadata, 'size_bytes' | 'checksum_sha256' | 'offline_available'> & {
    size_bytes: number;
    checksum_sha256: string;
    offline_available: number;
    offline: number;
    offlineVersion: number | null;
    access_expires_at: string | null;
    last_server_time: string | null;
  }>(
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
        AND ${scopeClause}
        AND d.id = ?
        AND d.revoked_at IS NULL
      LIMIT 1`,
    namespace,
    tripId,
    ...ownershipParameters,
    documentId,
  );
  if (
    row?.access_expires_at
    && isAccessLeaseExpired({
      accessExpiresAt: row.access_expires_at,
      lastServerTime: row.last_server_time,
    }, Date.now())
  ) return null;
  if (!row) return null;
  const {
    access_expires_at: _accessExpiresAt,
    last_server_time: _lastServerTime,
    ...documentRow
  } = row;
  return {
    ...documentRow,
    size_bytes: row.metadata_state === 'ready' ? row.size_bytes : null,
    checksum_sha256: row.metadata_state === 'ready' ? row.checksum_sha256 : null,
    offline_available: Boolean(row.offline_available),
    offline: Boolean(row.offline),
    offlineVersion: row.offlineVersion,
  };
}

export async function refreshDocuments(tripId: string, syncContext?: ImmutableSyncContext) {
  try {
    if (syncContext) assertSyncContextActive(syncContext);
    const items = await collectCursorItems(
      (cursor) => {
        if (syncContext) assertSyncContextActive(syncContext);
        return apiRequest(
          `/mobile/trips/${tripId}/documents?limit=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`,
          {
            schema: DocumentListSchema,
            ...(syncContext ? { signal: syncContext.signal } : {}),
          },
        );
      },
      { maxPages: 20, maxItems: 4_000 },
    );
    if (syncContext) assertSyncContextActive(syncContext);
    await saveDocuments(tripId, items, 'personal', syncContext);
    return { items: await localDocuments(tripId, syncContext), offline: false };
  } catch (networkError) {
    if (syncContext) assertSyncContextActive(syncContext);
    const items = await localDocuments(tripId, syncContext);
    if (items.length) return { items, offline: true };
    throw networkError;
  }
}

export async function refreshCommonDocuments(tripId: string, syncContext?: ImmutableSyncContext) {
  try {
    if (syncContext) assertSyncContextActive(syncContext);
    const commonItems = await collectCursorItems(
      (cursor) => {
        if (syncContext) assertSyncContextActive(syncContext);
        return apiRequest(
          `/mobile/trips/${tripId}/common-documents?limit=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`,
          {
            schema: CommonDocumentListSchema,
            ...(syncContext ? { signal: syncContext.signal } : {}),
          },
        );
      },
      { maxPages: 20, maxItems: 4_000 },
    );
    if (syncContext) assertSyncContextActive(syncContext);
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
    await saveDocuments(tripId, documents, 'common', syncContext);
    return { items: await localDocuments(tripId, syncContext, 'common'), offline: false };
  } catch (networkError) {
    if (syncContext) assertSyncContextActive(syncContext);
    const items = await localDocuments(tripId, syncContext, 'common');
    if (items.length) return { items, offline: true };
    throw networkError;
  }
}

export async function refreshQr(tripId: string, syncContext?: ImmutableSyncContext) {
  const namespace = activeNamespace(syncContext);
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  let qr;
  try {
    qr = await apiRequest(`/mobile/trips/${tripId}/qr`, {
      schema: PersonalQrSchema,
      ...(syncContext ? { signal: syncContext.signal } : {}),
    });
    if (syncContext) assertSyncContextActive(syncContext);
  } catch (error) {
    if (syncContext) assertSyncContextActive(syncContext);
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

export async function localQr(tripId: string, syncContext?: ImmutableSyncContext) {
  const namespace = activeNamespace(syncContext);
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
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

export async function loadQr(tripId: string, syncContext?: ImmutableSyncContext) {
  try {
    return await refreshQr(tripId, syncContext);
  } catch (networkError) {
    if (syncContext) assertSyncContextActive(syncContext);
    const qr = await localQr(tripId, syncContext);
    if (qr) return { qr, offline: true };
    throw networkError;
  }
}

export async function loadRoom(tripId: string, syncContext?: ImmutableSyncContext) {
  const namespace = activeNamespace(syncContext);
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  try {
    const room = await apiRequest(`/mobile/trips/${tripId}/room`, {
      schema: RoomSchema,
      ...(syncContext ? { signal: syncContext.signal } : {}),
    });
    if (syncContext) assertSyncContextActive(syncContext);
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
    if (syncContext) assertSyncContextActive(syncContext);
    const room = await localRoom(tripId, syncContext);
    if (room) return room;
    throw networkError;
  }
}

export async function localRoom(tripId: string, syncContext?: ImmutableSyncContext) {
  const namespace = activeNamespace(syncContext);
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  const room = await database.getFirstAsync<{
    id: string; passenger_id: string | null; hotel_name: string | null; room_number: string | null;
    roommate_summary: string | null; version: number; updated_at: string;
  }>('SELECT id, passenger_id, hotel_name, room_number, roommate_summary, version, updated_at FROM room_assignments WHERE account_namespace = ? AND trip_id = ? ORDER BY version DESC LIMIT 1', namespace, tripId);
  return room ? { ...room, trip_id: tripId, offline: true as const } : null;
}

export async function loadMeal(tripId: string, syncContext?: ImmutableSyncContext) {
  const namespace = activeNamespace(syncContext);
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  try {
    const meal = await apiRequest(`/mobile/trips/${tripId}/meals`, {
      schema: MealSchema,
      ...(syncContext ? { signal: syncContext.signal } : {}),
    });
    if (syncContext) assertSyncContextActive(syncContext);
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
    if (syncContext) assertSyncContextActive(syncContext);
    const meal = await localMeal(tripId, syncContext);
    if (meal) return meal;
    throw networkError;
  }
}

export async function localMeal(tripId: string, syncContext?: ImmutableSyncContext) {
  const namespace = activeNamespace(syncContext);
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  const meal = await database.getFirstAsync<{
    id: string; passenger_id: string | null; preference: string | null; notes: string | null;
    version: number; updated_at: string;
  }>('SELECT id, passenger_id, preference, notes, version, updated_at FROM meal_information WHERE account_namespace = ? AND trip_id = ? ORDER BY version DESC LIMIT 1', namespace, tripId);
  return meal ? { ...meal, trip_id: tripId, offline: true as const } : null;
}

export async function loadReadiness(tripId: string, syncContext?: ImmutableSyncContext) {
  const namespace = activeNamespace(syncContext);
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  try {
    const readiness = await apiRequest(`/mobile/manager/groups/${tripId}/readiness`, {
      schema: ReadinessSchema,
      ...(syncContext ? { signal: syncContext.signal } : {}),
    });
    if (syncContext) assertSyncContextActive(syncContext);
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
    if (syncContext) assertSyncContextActive(syncContext);
    const readiness = await localReadiness(tripId, syncContext);
    if (readiness) return readiness;
    throw networkError;
  }
}

export async function localReadiness(tripId: string, syncContext?: ImmutableSyncContext) {
  const namespace = activeNamespace(syncContext);
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  const readiness = await database.getFirstAsync<{
    passenger_count: number; passports_complete: number; visas_available: number; tickets_available: number;
    items_needing_attention: number; rooms_assigned: number; meals_confirmed: number; version: number; updated_at: string;
  }>('SELECT passenger_count, passports_complete, visas_available, tickets_available, items_needing_attention, rooms_assigned, meals_confirmed, version, updated_at FROM manager_readiness WHERE account_namespace = ? AND trip_id = ?', namespace, tripId);
  return readiness ? { ...readiness, trip_id: tripId, offline: true as const } : null;
}

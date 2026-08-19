import { apiRequest, ApiError } from '@/core/api/client';
import { principalAccountNamespace, type MobilePrincipal } from '@/core/auth/types';
import { useSessionStore } from '@/core/auth/session-store';
import { mobileQueryClient } from '@/core/query/query-client';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';
import {
  assertSyncContextActive,
  isSyncContextChanged,
  type ImmutableSyncContext,
} from '@/core/sync/sync-context';
import { isAccessLeaseExpired } from '@/core/sync/access-expiry-policy';
import {
  discardEncryptedOfflineFile,
  deleteVaultQuotaEvictionCandidates,
  downloadAndEncryptDocument,
  finalizeEncryptedOfflineFile,
  inspectRegisteredOfflineFile,
  isLocalOfflineCiphertextError,
  reconcileTripVault,
  removeRegisteredOfflineFile,
  type EncryptedOfflineFile,
  type VaultQuotaEvictionCandidate,
  type VaultStorageQuotaReclaimer,
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
import {
  acknowledgeVaultEvictionTombstones,
  detachVaultQuotaCandidates,
  markOfflineFileOpened,
  queryVaultEvictionTombstones,
  queryVaultQuotaCandidates,
  recordVaultEvictionAttempt,
} from './vault-quota-database';
import {
  queryDocument,
  queryLocalDocuments,
  queryOfflineDocumentRegistration,
  queryRetryableOfflineDocuments,
  queryStoredDocumentForCache,
  queryTripVaultState,
  replaceDocumentsInTransaction,
  type DocumentOwnershipFilter,
  type DocumentWithOfflineState,
  type RetryableOfflineDocument,
} from './document-database';
import {
  deletePersonalQr,
  markAnnouncementReadInDatabase,
  queryAnnouncements,
  queryMealInformation,
  queryPersonalQr,
  queryReadiness,
  queryRoomAssignment,
  replaceAnnouncementsInTransaction,
  replaceMealInformationInTransaction,
  replaceRoomAssignmentInTransaction,
  savePersonalQr,
  saveReadiness,
} from './content-resource-database';
import { useCoordinatorTripStore } from '@/features/coordinator/state/coordinator-trip-store';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

export type { DocumentWithOfflineState } from './document-database';

const documentDownloads = new Map<string, Promise<void>>();
const recoveredTripVaults = new Set<string>();
const vaultRecoveryJobs = new Map<string, Promise<void>>();
const vaultEvictionRecoveryJobs = new Map<string, Promise<void>>();
const MAX_DURABLE_DOCUMENT_RETRY_DELAY_MS = 6 * 60 * 60 * 1_000;

class AuthoritativeDocumentUnavailableError extends Error {
  readonly code = 'DOCUMENT_UNAVAILABLE';

  constructor(cause?: unknown) {
    super('This document is no longer available for the selected trip.', { cause });
    this.name = 'AuthoritativeDocumentUnavailableError';
  }
}

function isAuthoritativeDocumentUnavailable(error: unknown): boolean {
  return error instanceof AuthoritativeDocumentUnavailableError
    || (
      error instanceof ApiError
      && (
        (error.status === 404 && error.code === 'NOT_FOUND')
        || (
          error.status === 410
          && ['DOCUMENT_GONE', 'DOCUMENT_REVOKED'].includes(error.code)
        )
      )
    );
}

type AccountDatabase = Awaited<ReturnType<typeof openAccountDatabase>>;

async function reconcileRegisteredTripVault(
  database: AccountDatabase,
  namespace: string,
  tripId: string,
): Promise<void> {
  // Query first and let any database failure abort cleanup. The vault validates every selected
  // path before deleting anything, so corrupt or cross-namespace state always fails closed.
  const { registeredUris, resumableDocuments } = await queryTripVaultState(
    database,
    namespace,
    tripId,
  );
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

async function recoverVaultEvictionsForAccount(
  database: AccountDatabase,
  namespace: string,
): Promise<void> {
  const existing = vaultEvictionRecoveryJobs.get(namespace);
  if (existing) return existing;
  const recovery = (async () => {
    const tombstones = await queryVaultEvictionTombstones(database, namespace);
    if (!tombstones.length) return;
    try {
      await deleteVaultQuotaEvictionCandidates(namespace, tombstones);
      await withAccountTransaction(database, (transaction) => (
        acknowledgeVaultEvictionTombstones(transaction, namespace, tombstones)
      ));
    } catch (error) {
      await recordVaultEvictionAttempt(
        database,
        namespace,
        tombstones,
        new Date().toISOString(),
      ).catch(() => undefined);
      throw error;
    }
  })().finally(() => {
    if (vaultEvictionRecoveryJobs.get(namespace) === recovery) {
      vaultEvictionRecoveryJobs.delete(namespace);
    }
  });
  vaultEvictionRecoveryJobs.set(namespace, recovery);
  return recovery;
}

/** Retry crash-left native deletions for the active account without crossing its database. */
export async function recoverPendingVaultEvictions(): Promise<void> {
  const namespace = activeNamespace();
  const database = await openAccountDatabase(namespace);
  await recoverVaultEvictionsForAccount(database, namespace);
}

function protectedVaultTripIds(namespace: string, requestedTripId: string): string[] {
  const protectedTrips = new Set([requestedTripId]);
  const selectedPassengerTrip = useSelectedTripStore.getState().tripId;
  if (selectedPassengerTrip) protectedTrips.add(selectedPassengerTrip);
  const selectedCoordinatorTrip = useCoordinatorTripStore.getState();
  if (
    selectedCoordinatorTrip.accountKey === namespace
    && selectedCoordinatorTrip.tripId
  ) {
    protectedTrips.add(selectedCoordinatorTrip.tripId);
  }
  return [...protectedTrips];
}

function vaultQuotaReclaimer(
  database: AccountDatabase,
  namespace: string,
  requestedTripId: string,
  syncContext?: ImmutableSyncContext,
): VaultStorageQuotaReclaimer {
  const assertActive = () => {
    if (syncContext) assertSyncContextActive(syncContext);
  };
  return {
    listCandidates: async () => {
      assertActive();
      await recoverVaultEvictionsForAccount(database, namespace);
      assertActive();
      return queryVaultQuotaCandidates(
        database,
        namespace,
        protectedVaultTripIds(namespace, requestedTripId),
      );
    },
    evict: async (candidates: readonly VaultQuotaEvictionCandidate[]) => {
      assertActive();
      const detachedAt = new Date().toISOString();
      await withAccountTransaction(database, async (transaction) => {
        assertActive();
        await detachVaultQuotaCandidates(transaction, namespace, candidates, detachedAt);
        assertActive();
      });
      try {
        await deleteVaultQuotaEvictionCandidates(namespace, candidates);
        assertActive();
        await withAccountTransaction(database, async (transaction) => {
          assertActive();
          await acknowledgeVaultEvictionTombstones(transaction, namespace, candidates);
        });
      } catch (error) {
        await recordVaultEvictionAttempt(
          database,
          namespace,
          candidates,
          new Date().toISOString(),
        ).catch(() => undefined);
        throw error;
      }
    },
  };
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

function documentOwnershipFilter(principal: MobilePrincipal): DocumentOwnershipFilter {
  return principal.principalType === 'passenger'
    ? {
      sql: "AND (d.scope = 'common' OR (d.scope = 'personal' AND d.passenger_id = ?))",
      parameters: [principal.passengerId!],
    }
    : { sql: "AND d.scope = 'common'", parameters: [] };
}

async function saveAnnouncements(
  tripId: string,
  announcements: Announcement[],
  syncContext?: ImmutableSyncContext,
): Promise<void> {
  const namespace = activeNamespace(syncContext);
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  await withAccountTransaction(database, (transaction) => replaceAnnouncementsInTransaction(
    transaction,
    {
      namespace,
      tripId,
      announcements,
      ...(syncContext ? {
        assertActive: () => assertSyncContextActive(syncContext),
      } : {}),
    },
  ));
}

export async function localAnnouncements(
  tripId: string,
  syncContext?: ImmutableSyncContext,
): Promise<Announcement[]> {
  const namespace = activeNamespace(syncContext);
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  return queryAnnouncements(database, namespace, tripId);
}

function cursorResourcePath(path: string, cursor: string | null): string {
  const separator = path.includes('?') ? '&' : '?';
  return `${path}${separator}limit=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`;
}

export async function refreshAnnouncements(
  tripId: string,
  syncContext?: ImmutableSyncContext,
  requestPath = `/mobile/trips/${tripId}/announcements`,
) {
  try {
    if (syncContext) assertSyncContextActive(syncContext);
    const items = await collectCursorItems(
      (cursor) => {
        if (syncContext) assertSyncContextActive(syncContext);
        return apiRequest(cursorResourcePath(requestPath, cursor), {
            schema: AnnouncementListSchema,
            ...(syncContext ? { signal: syncContext.signal } : {}),
        });
      },
      {
        itemKey: (announcement) => announcement.id,
        ...(syncContext ? {
          assertActive: () => assertSyncContextActive(syncContext),
        } : {}),
      },
    );
    if (syncContext) assertSyncContextActive(syncContext);
    await saveAnnouncements(tripId, items, syncContext);
    return { items, offline: false };
  } catch (networkError) {
    if (syncContext) assertSyncContextActive(syncContext);
    if (syncContext) throw networkError;
    const items = await localAnnouncements(tripId, syncContext);
    if (items.length) return { items, offline: true };
    throw networkError;
  }
}

export async function markAnnouncementRead(announcementId: string): Promise<void> {
  const namespace = activeNamespace();
  const database = await openAccountDatabase(namespace);
  await markAnnouncementReadInDatabase(database, namespace, announcementId);
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
  await withAccountTransaction(database, (transaction) => replaceDocumentsInTransaction(
    transaction,
    {
      namespace,
      tripId,
      scope,
      documents,
      nowIso: new Date().toISOString(),
      ...(syncContext ? {
        assertActive: () => assertSyncContextActive(syncContext),
      } : {}),
    },
  ));
  if (syncContext) assertSyncContextActive(syncContext);
  await reconcileRegisteredTripVault(database, namespace, tripId);
}

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
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  await recoverTripVaultOnce(database, namespace, tripId);
  if (syncContext) assertSyncContextActive(syncContext);
  return queryLocalDocuments(database, {
    namespace,
    tripId,
    ownership: documentOwnershipFilter(principal),
    ...(scope ? { scope } : {}),
  });
}

type CachedDocumentCollection = Readonly<{
  items: readonly DocumentWithOfflineState[];
  offline: boolean;
}>;

function removeDocumentFromQueryCache(
  namespace: string,
  tripId: string,
  documentId: string,
): void {
  for (const prefix of ['trip-documents', 'trip-common-documents'] as const) {
    const queryKey = [prefix, tripId, namespace] as const;
    mobileQueryClient.setQueryData<CachedDocumentCollection>(queryKey, (current) => (
      current
        ? { ...current, items: current.items.filter((item) => item.id !== documentId) }
        : current
    ));
    void mobileQueryClient.invalidateQueries({ queryKey }).catch(() => undefined);
  }
}

/**
 * Reconciles an exact document revision after its signed authorization endpoint
 * authoritatively reports that it was deleted or withdrawn.
 *
 * The deletion is constrained to the active account, trip, revision, and role
 * ownership boundary. SQLite makes the metadata, retry job, and offline-file
 * registration unreachable atomically; managed ciphertext is then removed by
 * the normal path-validating vault reconciler.
 */
export async function reconcileUnavailableDocument(
  document: Pick<
    DocumentMetadata,
    'id' | 'trip_id' | 'passenger_id' | 'scope' | 'version'
  >,
  syncContext?: ImmutableSyncContext,
): Promise<boolean> {
  const principal = useSessionStore.getState().session?.principal;
  if (!principal) throw new Error('Authentication is required.');
  if (principal.principalType === 'passenger' && !principal.passengerId) {
    throw new Error('The passenger ownership boundary is unavailable. Sign in again while online.');
  }
  if (
    document.scope === 'personal'
    && (
      principal.principalType !== 'passenger'
      || !principal.passengerId
      || document.passenger_id !== principal.passengerId
    )
  ) {
    throw new Error('The personal document does not belong to the active passenger.');
  }

  const namespace = activeNamespace(syncContext);
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  let removed = false;
  await withAccountTransaction(database, async (transaction) => {
    if (syncContext) assertSyncContextActive(syncContext);
    const ownershipClause = principal.principalType === 'passenger'
      ? "AND (scope = 'common' OR (scope = 'personal' AND passenger_id = ?))"
      : "AND scope = 'common'";
    const ownershipParameters = principal.principalType === 'passenger'
      ? [principal.passengerId!]
      : [];
    const result = await transaction.runAsync(
      `DELETE FROM document_metadata
        WHERE account_namespace = ? AND trip_id = ? AND id = ? AND version = ?
          AND revoked_at IS NULL
          ${ownershipClause}`,
      namespace,
      document.trip_id,
      document.id,
      document.version,
      ...ownershipParameters,
    );
    removed = result.changes === 1;
  });
  if (!removed) return false;

  removeDocumentFromQueryCache(namespace, document.trip_id, document.id);
  const recoveryKey = `${namespace}:${document.trip_id}`;
  recoveredTripVaults.delete(recoveryKey);
  // The database deletion already made both metadata and the cascaded vault
  // registration unreachable. Physical removal is best effort here: if the
  // filesystem is temporarily unavailable, the cleared recovery marker makes
  // the next trip read retry path-validated orphan cleanup without restoring
  // the withdrawn document to the UI.
  await reconcileRegisteredTripVault(database, namespace, document.trip_id).catch(() => undefined);
  return true;
}

export async function cacheDocument(
  document: DocumentMetadata,
  syncContext?: ImmutableSyncContext,
  signal?: AbortSignal,
  retentionClass: 'required' | 'evictable' = 'evictable',
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
        return cacheDocument(document, syncContext, signal, retentionClass);
      }
      throw error;
    }
    if (syncContext) assertSyncContextActive(syncContext);
    assertDocumentOperationActive(operationSignal);
    return cacheDocument(document, syncContext, signal, retentionClass);
  }

  const download = cacheDocumentForNamespace(
    namespace,
    document,
    syncContext,
    operationSignal,
    retentionClass,
  ).catch(async (error: unknown) => {
    if (!isAuthoritativeDocumentUnavailable(error)) throw error;
    await reconcileUnavailableDocument(document, syncContext);
    throw new AuthoritativeDocumentUnavailableError(error);
  }).finally(() => {
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
  retentionClass: 'required' | 'evictable' = 'evictable',
): Promise<void> {
  assertDocumentOperationActive(signal);
  if (syncContext) assertSyncContextActive(syncContext);
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  const stored = await queryStoredDocumentForCache(
    database,
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
    throw new Error('This document is still being prepared for offline use.');
  }

  const current = await queryOfflineDocumentRegistration(
    database,
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
      await withAccountTransaction(database, async (transaction) => {
        if (retentionClass === 'required') {
          await transaction.runAsync(
            `UPDATE offline_files SET retention_class = 'required'
              WHERE document_id = ? AND account_namespace = ? AND trip_id = ? AND version = ?`,
            document.id,
            namespace,
            stored.trip_id,
            document.version,
          );
        }
        await transaction.runAsync(
          `DELETE FROM offline_document_jobs
            WHERE document_id = ? AND account_namespace = ? AND trip_id = ? AND version = ?`,
          document.id,
          namespace,
          stored.trip_id,
          document.version,
        );
      });
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
    }, signal, vaultQuotaReclaimer(
      database,
      namespace,
      stored.trip_id,
      syncContext,
    ));
    encrypted = downloaded;
    if (syncContext) assertSyncContextActive(syncContext);
    assertDocumentOperationActive(signal);
    // downloadAndEncryptDocument authenticates every written AES-GCM frame and
    // verifies the complete signed plaintext checksum before atomically moving
    // the candidate into its immutable final path. Re-reading and decrypting the
    // same file here doubled CPU and I/O without adding an independent trust
    // boundary. Existing registrations are still fully inspected above, and
    // every viewer authenticates the ciphertext again before exposing plaintext.
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
           encrypted_size_bytes, downloaded_at, last_opened_at, retention_class)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
         ON CONFLICT(document_id) DO UPDATE SET
           account_namespace = excluded.account_namespace,
           trip_id = excluded.trip_id,
           version = excluded.version,
           encrypted_path = excluded.encrypted_path,
           checksum_sha256 = excluded.checksum_sha256,
           encrypted_size_bytes = excluded.encrypted_size_bytes,
           downloaded_at = excluded.downloaded_at,
           last_opened_at = NULL,
           retention_class = CASE
             WHEN offline_files.retention_class = 'required' THEN 'required'
             ELSE excluded.retention_class
           END`,
        document.id,
        namespace,
        stored.trip_id,
        document.version,
        downloaded.uri,
        downloaded.checksumSha256,
        downloaded.encryptedSizeBytes,
        new Date().toISOString(),
        retentionClass,
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
  if (isAuthoritativeDocumentUnavailable(error)) {
    return { code: 'DOCUMENT_UNAVAILABLE', retryable: false };
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
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  return queryRetryableOfflineDocuments(database, {
    namespace,
    tripId,
    scopes: [...scopes],
    ownership: documentOwnershipFilter(principal),
    includeDeferred,
    nowIso: new Date().toISOString(),
  });
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
      await cacheDocument(candidate, syncContext, signal, 'required');
      return;
    } catch (error) {
      if (syncContext) assertSyncContextActive(syncContext);
      // An authoritative withdrawal was already removed transactionally by
      // cacheDocument. Treat that reconciliation as completed work rather than
      // recreating a durable retry for an object that no longer exists.
      if (error instanceof AuthoritativeDocumentUnavailableError) return;
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
  const lookup = await queryDocument(database, {
    namespace,
    tripId,
    documentId,
    ownership: documentOwnershipFilter(principal),
  });
  if (
    lookup?.accessExpiresAt
    && isAccessLeaseExpired({
      accessExpiresAt: lookup.accessExpiresAt,
      lastServerTime: lookup.lastServerTime,
    }, Date.now())
  ) return null;
  return lookup?.document ?? null;
}

/** Record a successful authenticated decrypt, not a list view or background prefetch. */
export async function recordOfflineDocumentOpened(options: Readonly<{
  namespace: string;
  tripId: string;
  documentId: string;
  version: number;
}>): Promise<void> {
  const principal = useSessionStore.getState().session?.principal;
  if (!principal || principalAccountNamespace(principal) !== options.namespace) {
    throw new Error('The document access no longer belongs to the active account.');
  }
  const database = await openAccountDatabase(options.namespace);
  await withAccountTransaction(database, async (transaction) => {
    await markOfflineFileOpened(transaction, {
      ...options,
      openedAtIso: new Date().toISOString(),
    });
  });
}

export async function refreshDocuments(
  tripId: string,
  syncContext?: ImmutableSyncContext,
  requestPath = `/mobile/trips/${tripId}/documents`,
) {
  try {
    if (syncContext) assertSyncContextActive(syncContext);
    const items = await collectCursorItems(
      (cursor) => {
        if (syncContext) assertSyncContextActive(syncContext);
        return apiRequest(cursorResourcePath(requestPath, cursor), {
            schema: DocumentListSchema,
            ...(syncContext ? { signal: syncContext.signal } : {}),
        });
      },
      {
        itemKey: (document) => document.id,
        ...(syncContext ? {
          assertActive: () => assertSyncContextActive(syncContext),
        } : {}),
      },
    );
    if (syncContext) assertSyncContextActive(syncContext);
    await saveDocuments(tripId, items, 'personal', syncContext);
    return { items: await localDocuments(tripId, syncContext), offline: false };
  } catch (networkError) {
    if (syncContext) assertSyncContextActive(syncContext);
    if (syncContext) throw networkError;
    const items = await localDocuments(tripId, syncContext);
    if (items.length) return { items, offline: true };
    throw networkError;
  }
}

export async function refreshCommonDocuments(
  tripId: string,
  syncContext?: ImmutableSyncContext,
  requestPath = `/mobile/trips/${tripId}/common-documents`,
) {
  try {
    if (syncContext) assertSyncContextActive(syncContext);
    const commonItems = await collectCursorItems(
      (cursor) => {
        if (syncContext) assertSyncContextActive(syncContext);
        return apiRequest(cursorResourcePath(requestPath, cursor), {
            schema: CommonDocumentListSchema,
            ...(syncContext ? { signal: syncContext.signal } : {}),
        });
      },
      {
        itemKey: (document) => document.id,
        ...(syncContext ? {
          assertActive: () => assertSyncContextActive(syncContext),
        } : {}),
      },
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
    if (syncContext) throw networkError;
    const items = await localDocuments(tripId, syncContext, 'common');
    if (items.length) return { items, offline: true };
    throw networkError;
  }
}

export async function refreshQr(
  tripId: string,
  syncContext?: ImmutableSyncContext,
  requestPath = `/mobile/trips/${tripId}/qr`,
) {
  const namespace = activeNamespace(syncContext);
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  let qr;
  try {
    qr = await apiRequest(requestPath, {
      schema: PersonalQrSchema,
      ...(syncContext ? { signal: syncContext.signal } : {}),
    });
    if (syncContext) assertSyncContextActive(syncContext);
  } catch (error) {
    if (syncContext) assertSyncContextActive(syncContext);
    if (error instanceof ApiError && error.status === 404 && error.code === 'NOT_FOUND') {
      await withAccountTransaction(database, async (transaction) => {
        if (syncContext) assertSyncContextActive(syncContext);
        await deletePersonalQr(transaction, namespace, tripId);
        if (syncContext) assertSyncContextActive(syncContext);
      });
      return { qr: null, offline: false };
    }
    throw error;
  }
  await withAccountTransaction(database, async (transaction) => {
    if (syncContext) assertSyncContextActive(syncContext);
    await savePersonalQr(transaction, namespace, tripId, qr);
    if (syncContext) assertSyncContextActive(syncContext);
  });
  return { qr, offline: false };
}

export async function localQr(tripId: string, syncContext?: ImmutableSyncContext) {
  const namespace = activeNamespace(syncContext);
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  return queryPersonalQr(database, namespace, tripId, new Date().toISOString());
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

export async function loadRoom(
  tripId: string,
  syncContext?: ImmutableSyncContext,
  requestPath = `/mobile/trips/${tripId}/room`,
) {
  const namespace = activeNamespace(syncContext);
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  try {
    const room = await apiRequest(requestPath, {
      schema: RoomSchema,
      ...(syncContext ? { signal: syncContext.signal } : {}),
    });
    if (syncContext) assertSyncContextActive(syncContext);
    await withAccountTransaction(database, async (transaction) => {
      if (syncContext) assertSyncContextActive(syncContext);
      await replaceRoomAssignmentInTransaction(transaction, namespace, tripId, room);
      if (syncContext) assertSyncContextActive(syncContext);
    });
    return { ...room, offline: false };
  } catch (networkError) {
    if (syncContext) assertSyncContextActive(syncContext);
    if (syncContext) throw networkError;
    const room = await localRoom(tripId, syncContext);
    if (room) return room;
    throw networkError;
  }
}

export async function localRoom(tripId: string, syncContext?: ImmutableSyncContext) {
  const namespace = activeNamespace(syncContext);
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  return queryRoomAssignment(database, namespace, tripId);
}

export async function loadMeal(
  tripId: string,
  syncContext?: ImmutableSyncContext,
  requestPath = `/mobile/trips/${tripId}/meals`,
) {
  const namespace = activeNamespace(syncContext);
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  try {
    const meal = await apiRequest(requestPath, {
      schema: MealSchema,
      ...(syncContext ? { signal: syncContext.signal } : {}),
    });
    if (syncContext) assertSyncContextActive(syncContext);
    await withAccountTransaction(database, async (transaction) => {
      if (syncContext) assertSyncContextActive(syncContext);
      await replaceMealInformationInTransaction(transaction, namespace, tripId, meal);
      if (syncContext) assertSyncContextActive(syncContext);
    });
    return { ...meal, offline: false };
  } catch (networkError) {
    if (syncContext) assertSyncContextActive(syncContext);
    if (syncContext) throw networkError;
    const meal = await localMeal(tripId, syncContext);
    if (meal) return meal;
    throw networkError;
  }
}

export async function localMeal(tripId: string, syncContext?: ImmutableSyncContext) {
  const namespace = activeNamespace(syncContext);
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  return queryMealInformation(database, namespace, tripId);
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
    await saveReadiness(database, namespace, tripId, readiness);
    return { ...readiness, offline: false };
  } catch (networkError) {
    if (syncContext) assertSyncContextActive(syncContext);
    if (syncContext) throw networkError;
    const readiness = await localReadiness(tripId, syncContext);
    if (readiness) return readiness;
    throw networkError;
  }
}

export async function localReadiness(tripId: string, syncContext?: ImmutableSyncContext) {
  const namespace = activeNamespace(syncContext);
  const database = await openAccountDatabase(namespace);
  if (syncContext) assertSyncContextActive(syncContext);
  return queryReadiness(database, namespace, tripId);
}

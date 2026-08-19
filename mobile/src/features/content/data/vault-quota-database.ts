import type * as SQLite from 'expo-sqlite';

import type { VaultQuotaEvictionCandidate } from '@/core/storage/vault';

export const MAX_VAULT_QUOTA_CANDIDATES = 512;
export const MAX_VAULT_EVICTION_RECOVERY_BATCH = 64;

type VaultQuotaCandidateRow = {
  encrypted_path: string;
  account_namespace: string;
  trip_id: string;
  document_id: string;
  version: number;
  checksum_sha256: string;
  encrypted_size_bytes: number;
  downloaded_at: string;
  last_opened_at: string | null;
};

export type VaultEvictionTombstone = VaultQuotaEvictionCandidate & Readonly<{
  attemptCount: number;
}>;

function timestamp(value: string, label: string): number {
  const parsed = Date.parse(value);
  if (!Number.isSafeInteger(parsed) || parsed < 0) {
    throw new Error(`A vault ${label} timestamp is invalid.`);
  }
  return parsed;
}

function mapCandidate(row: VaultQuotaCandidateRow): VaultQuotaEvictionCandidate {
  return {
    encryptedUri: row.encrypted_path,
    namespace: row.account_namespace,
    tripId: row.trip_id,
    documentId: row.document_id,
    version: row.version,
    checksumSha256: row.checksum_sha256,
    encryptedSizeBytes: row.encrypted_size_bytes,
    retentionClass: 'evictable',
    downloadedAtMs: timestamp(row.downloaded_at, 'download'),
    lastOpenedAtMs: row.last_opened_at === null
      ? null
      : timestamp(row.last_opened_at, 'last-opened'),
    protectedFromEviction: false,
  };
}

/** Returns only explicitly evictable, non-current files in deterministic LRU order. */
export async function queryVaultQuotaCandidates(
  database: SQLite.SQLiteDatabase,
  namespace: string,
  protectedTripIds: readonly string[],
): Promise<VaultQuotaEvictionCandidate[]> {
  if (!namespace) throw new Error('A vault account namespace is required.');
  const protectedTrips = [...new Set(protectedTripIds.filter(Boolean))];
  const exclusion = protectedTrips.length
    ? `AND trip_id NOT IN (${protectedTrips.map(() => '?').join(', ')})`
    : '';
  const rows = await database.getAllAsync<VaultQuotaCandidateRow>(
    `SELECT encrypted_path, account_namespace, trip_id, document_id, version,
            checksum_sha256, encrypted_size_bytes, downloaded_at, last_opened_at
       FROM offline_files
      WHERE account_namespace = ? AND retention_class = 'evictable'
        ${exclusion}
      ORDER BY COALESCE(last_opened_at, downloaded_at), downloaded_at, encrypted_path
      LIMIT ${MAX_VAULT_QUOTA_CANDIDATES}`,
    namespace,
    ...protectedTrips,
  );
  return rows.map(mapCandidate);
}

/**
 * Atomically makes selected registrations unreachable and records durable native cleanup work.
 * Any stale candidate rolls the whole transaction back through the caller's transaction runner.
 */
export async function detachVaultQuotaCandidates(
  transaction: SQLite.SQLiteDatabase,
  namespace: string,
  candidates: readonly VaultQuotaEvictionCandidate[],
  nowIso: string,
): Promise<void> {
  for (const candidate of candidates) {
    if (
      candidate.namespace !== namespace
      || candidate.retentionClass !== 'evictable'
      || candidate.protectedFromEviction === true
    ) {
      throw new Error('A protected or cross-account vault artifact cannot be detached.');
    }
    const tombstone = await transaction.runAsync(
      `INSERT INTO vault_eviction_tombstones
        (encrypted_path, account_namespace, trip_id, document_id, version, checksum_sha256,
         encrypted_size_bytes, created_at, last_attempt_at, attempt_count)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 0)
       ON CONFLICT(encrypted_path) DO UPDATE SET
         created_at = MIN(vault_eviction_tombstones.created_at, excluded.created_at)
       WHERE vault_eviction_tombstones.account_namespace = excluded.account_namespace
         AND vault_eviction_tombstones.trip_id = excluded.trip_id
         AND vault_eviction_tombstones.document_id = excluded.document_id
         AND vault_eviction_tombstones.version = excluded.version
         AND lower(vault_eviction_tombstones.checksum_sha256) = lower(excluded.checksum_sha256)`,
      candidate.encryptedUri,
      namespace,
      candidate.tripId,
      candidate.documentId,
      candidate.version,
      candidate.checksumSha256,
      candidate.encryptedSizeBytes,
      nowIso,
    );
    if (tombstone.changes !== 1) {
      throw new Error('A vault eviction tombstone conflicted with another account artifact.');
    }
    const detached = await transaction.runAsync(
      `DELETE FROM offline_files
        WHERE encrypted_path = ? AND account_namespace = ? AND trip_id = ?
          AND document_id = ? AND version = ?
          AND lower(checksum_sha256) = lower(?)
          AND encrypted_size_bytes = ? AND retention_class = 'evictable'`,
      candidate.encryptedUri,
      namespace,
      candidate.tripId,
      candidate.documentId,
      candidate.version,
      candidate.checksumSha256,
      candidate.encryptedSizeBytes,
    );
    if (detached.changes !== 1) {
      throw new Error('A vault eviction candidate changed before it could be detached.');
    }
  }
}

export async function queryVaultEvictionTombstones(
  database: SQLite.SQLiteDatabase,
  namespace: string,
): Promise<VaultEvictionTombstone[]> {
  const rows = await database.getAllAsync<VaultQuotaCandidateRow & { attempt_count: number }>(
    `SELECT encrypted_path, account_namespace, trip_id, document_id, version,
            checksum_sha256, encrypted_size_bytes, created_at AS downloaded_at,
            NULL AS last_opened_at, attempt_count
       FROM vault_eviction_tombstones
      WHERE account_namespace = ?
      ORDER BY created_at, encrypted_path
      LIMIT ${MAX_VAULT_EVICTION_RECOVERY_BATCH}`,
    namespace,
  );
  return rows.map((row) => ({ ...mapCandidate(row), attemptCount: row.attempt_count }));
}

export async function acknowledgeVaultEvictionTombstones(
  transaction: SQLite.SQLiteDatabase,
  namespace: string,
  candidates: readonly VaultQuotaEvictionCandidate[],
): Promise<void> {
  for (const candidate of candidates) {
    await transaction.runAsync(
      `DELETE FROM vault_eviction_tombstones
        WHERE encrypted_path = ? AND account_namespace = ? AND trip_id = ?
          AND document_id = ? AND version = ?
          AND lower(checksum_sha256) = lower(?)`,
      candidate.encryptedUri,
      namespace,
      candidate.tripId,
      candidate.documentId,
      candidate.version,
      candidate.checksumSha256,
    );
  }
}

export function recordVaultEvictionAttempt(
  database: SQLite.SQLiteDatabase,
  namespace: string,
  candidates: readonly VaultQuotaEvictionCandidate[],
  nowIso: string,
): Promise<unknown> {
  if (!candidates.length) return Promise.resolve();
  const uris = candidates.map(() => '?').join(', ');
  return database.runAsync(
    `UPDATE vault_eviction_tombstones
        SET attempt_count = attempt_count + 1, last_attempt_at = ?
      WHERE account_namespace = ? AND encrypted_path IN (${uris})`,
    nowIso,
    namespace,
    ...candidates.map((candidate) => candidate.encryptedUri),
  );
}

export function markOfflineFileOpened(
  database: SQLite.SQLiteDatabase,
  options: Readonly<{
    namespace: string;
    tripId: string;
    documentId: string;
    version: number;
    openedAtIso: string;
  }>,
): Promise<unknown> {
  return database.runAsync(
    `UPDATE offline_files SET last_opened_at = ?
      WHERE account_namespace = ? AND trip_id = ? AND document_id = ? AND version = ?`,
    options.openedAtIso,
    options.namespace,
    options.tripId,
    options.documentId,
    options.version,
  );
}

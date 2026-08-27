import { randomUUID } from 'expo-crypto';
import type * as SQLite from 'expo-sqlite';

import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';

import type { DownloadQuality } from '../api/contracts';
import type { MyPhotosContext } from '../data/my-photos-context';
import {
  assertPhotoDownloadTransition,
  coalescePhotoDownloadRequests,
  photoDownloadClaimCounterIncrements,
  type PhotoDownloadState,
} from './download-policy';
import {
  PHOTO_DOWNLOAD_JOB_SELECT,
  mapPhotoDownloadRow,
  type PhotoDownloadBatch,
  type PhotoDownloadJob,
  type PhotoDownloadRow,
} from './photo-download-record';
import { assertCanonicalPhotoVaultUri } from './photo-vault';

export type { PhotoDownloadBatch, PhotoDownloadJob } from './photo-download-record';

async function getOwnedJob(
  database: SQLite.SQLiteDatabase,
  context: MyPhotosContext,
  id: string,
): Promise<PhotoDownloadJob | null> {
  const row = await database.getFirstAsync<PhotoDownloadRow>(
    `${PHOTO_DOWNLOAD_JOB_SELECT}
      WHERE id = ? AND account_namespace = ? AND trip_id = ? AND passenger_id = ?`,
    id,
    context.namespace,
    context.tripId,
    context.passengerId,
  );
  return row ? mapPhotoDownloadRow(row) : null;
}

export async function getPhotoDownload(
  context: MyPhotosContext,
  id: string,
): Promise<PhotoDownloadJob | null> {
  const database = await openAccountDatabase(context.namespace);
  return getOwnedJob(database, context, id);
}

export async function findPhotoDownload(
  context: MyPhotosContext,
  assetId: string,
  quality: DownloadQuality,
): Promise<PhotoDownloadJob | null> {
  const database = await openAccountDatabase(context.namespace);
  const row = await database.getFirstAsync<PhotoDownloadRow>(
    `${PHOTO_DOWNLOAD_JOB_SELECT}
      WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
        AND media_asset_id = ? AND quality = ? AND state != 'removed'
      LIMIT 1`,
    context.namespace,
    context.tripId,
    context.passengerId,
    assetId,
    quality,
  );
  return row ? mapPhotoDownloadRow(row) : null;
}

export type PhotoDownloadManifestCursor = Readonly<{
  createdAt: string;
  id: string;
}>;

export type CompletedPhotoDownloadCursor = Readonly<{
  completedAt: string;
  id: string;
  direction: 'older' | 'newer';
}>;

export type CompletedPhotoDownloadPage = Readonly<{
  items: readonly PhotoDownloadJob[];
  nextCursor: CompletedPhotoDownloadCursor | null;
  previousCursor: CompletedPhotoDownloadCursor | null;
}>;

function assertCompletedPhotoDownloadCursor(cursor: CompletedPhotoDownloadCursor): void {
  if (
    !cursor.id
    || cursor.id.length > 128
    || !Number.isFinite(Date.parse(cursor.completedAt))
    || !['older', 'newer'].includes(cursor.direction)
  ) {
    throw new Error('Completed photo manifest cursor is invalid.');
  }
}

export async function getPhotoDownloadReconciliationCursor(
  context: MyPhotosContext,
): Promise<PhotoDownloadManifestCursor | null> {
  const database = await openAccountDatabase(context.namespace);
  const row = await database.getFirstAsync<{
    cursor_created_at: string | null;
    cursor_id: string | null;
  }>(
    `SELECT cursor_created_at, cursor_id
       FROM my_photos_reconciliation_state
      WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?`,
    context.namespace,
    context.tripId,
    context.passengerId,
  );
  return row?.cursor_created_at && row.cursor_id
    ? { createdAt: row.cursor_created_at, id: row.cursor_id }
    : null;
}

export async function checkpointPhotoDownloadReconciliation(
  context: MyPhotosContext,
  cursor: PhotoDownloadManifestCursor | null,
  nowIso = new Date().toISOString(),
): Promise<void> {
  const database = await openAccountDatabase(context.namespace);
  await database.runAsync(
    `INSERT INTO my_photos_reconciliation_state
       (account_namespace, trip_id, passenger_id, cursor_created_at, cursor_id,
        cycle_started_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(account_namespace, trip_id, passenger_id) DO UPDATE SET
       cursor_created_at = excluded.cursor_created_at,
       cursor_id = excluded.cursor_id,
       cycle_started_at = CASE
         WHEN excluded.cursor_created_at IS NULL THEN excluded.cycle_started_at
         ELSE my_photos_reconciliation_state.cycle_started_at
       END,
       updated_at = excluded.updated_at`,
    context.namespace,
    context.tripId,
    context.passengerId,
    cursor?.createdAt ?? null,
    cursor?.id ?? null,
    nowIso,
    nowIso,
  );
}

export async function listPhotoDownloadManifestPage(
  context: MyPhotosContext,
  cursor: PhotoDownloadManifestCursor | null,
  limit = 50,
): Promise<Readonly<{
  items: readonly PhotoDownloadJob[];
  nextCursor: PhotoDownloadManifestCursor | null;
}>> {
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100) {
    throw new Error('Photo manifest page limit is invalid.');
  }
  const database = await openAccountDatabase(context.namespace);
  const rows = await database.getAllAsync<PhotoDownloadRow>(
    `${PHOTO_DOWNLOAD_JOB_SELECT}
      WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
        ${cursor ? 'AND (created_at > ? OR (created_at = ? AND id > ?))' : ''}
      ORDER BY created_at ASC, id ASC
      LIMIT ?`,
    context.namespace,
    context.tripId,
    context.passengerId,
    ...(cursor ? [cursor.createdAt, cursor.createdAt, cursor.id] : []),
    limit,
  );
  const items = rows.map(mapPhotoDownloadRow);
  const last = items.at(-1);
  return {
    items,
    nextCursor: items.length === limit && last
      ? { createdAt: last.createdAt, id: last.id }
      : null,
  };
}

/** A local-only, owner-scoped keyset page over completed encrypted copies.
 * The page is intentionally independent from cached/server gallery rows so a
 * returning passenger can reach every retained copy after ordinary sign-out.
 * Only manifest metadata is read; ciphertext is not decrypted for this list. */
export async function listCompletedPhotoDownloadsPage(
  context: MyPhotosContext,
  cursor: CompletedPhotoDownloadCursor | null,
  limit = 24,
): Promise<CompletedPhotoDownloadPage> {
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 60) {
    throw new Error('Completed photo manifest page limit is invalid.');
  }
  if (cursor) assertCompletedPhotoDownloadCursor(cursor);
  const database = await openAccountDatabase(context.namespace);
  const newer = cursor?.direction === 'newer';
  const rows = await database.getAllAsync<PhotoDownloadRow>(
    `${PHOTO_DOWNLOAD_JOB_SELECT}
      WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
        AND state = 'completed' AND completed_at IS NOT NULL
        ${cursor ? `AND (completed_at ${newer ? '>' : '<'} ? OR (completed_at = ? AND id ${newer ? '>' : '<'} ?))` : ''}
      ORDER BY completed_at ${newer ? 'ASC' : 'DESC'}, id ${newer ? 'ASC' : 'DESC'}
      LIMIT ?`,
    context.namespace,
    context.tripId,
    context.passengerId,
    ...(cursor ? [cursor.completedAt, cursor.completedAt, cursor.id] : []),
    limit + 1,
  );
  const hasDirectionalPage = rows.length > limit;
  const directionalItems = rows.slice(0, limit).map(mapPhotoDownloadRow);
  const items = newer ? directionalItems.reverse() : directionalItems;
  const first = items[0];
  const last = items.at(-1);
  return {
    items,
    previousCursor: first && (newer ? hasDirectionalPage : Boolean(cursor))
      ? { completedAt: first.completedAt!, id: first.id, direction: 'newer' }
      : null,
    nextCursor: last && (newer ? Boolean(cursor) : hasDirectionalPage)
      ? { completedAt: last.completedAt!, id: last.id, direction: 'older' }
      : null,
  };
}

export async function listPhotoDownloads(
  context: MyPhotosContext,
  includeRemoved = false,
  limit = 250,
): Promise<PhotoDownloadJob[]> {
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 500) {
    throw new Error('Photo download page limit is invalid.');
  }
  const database = await openAccountDatabase(context.namespace);
  const rows = await database.getAllAsync<PhotoDownloadRow>(
    `${PHOTO_DOWNLOAD_JOB_SELECT}
      WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
        ${includeRemoved ? '' : "AND state != 'removed'"}
      ORDER BY
        CASE
          WHEN state IN ('completed', 'cancelled', 'failed', 'corrupt', 'removed') THEN 1
          ELSE 0
        END ASC,
        updated_at DESC,
        id DESC
      LIMIT ?`,
    context.namespace,
    context.tripId,
    context.passengerId,
    limit,
  );
  return rows.map(mapPhotoDownloadRow);
}

export type PhotoDownloadRetainedProgress = Readonly<{
  completedItemCount: number;
  verifiedPlaintextBytes: number;
}>;

/** Returns durable completed progress for one exact, bounded asset selection.
 * Download All deliberately cannot call this with a trip-wide aggregate:
 * revision membership is not proven until cursor enumeration commits each
 * asset, so its preflight conservatively grants zero retained-byte credit. */
export async function photoDownloadRetainedProgress(
  context: MyPhotosContext,
  quality: DownloadQuality,
  assetIds: readonly string[],
): Promise<PhotoDownloadRetainedProgress> {
  const identities = [...new Set(assetIds)];
  if (!identities.length) return { completedItemCount: 0, verifiedPlaintextBytes: 0 };
  if (identities.length > 500) throw new Error('Photo progress selection is too large.');
  const database = await openAccountDatabase(context.namespace);
  const chunks = Array.from({ length: Math.ceil(identities.length / 100) }, (_value, index) => (
    identities.slice(index * 100, index * 100 + 100)
  ));
  let completedItemCount = 0;
  let verifiedPlaintextBytes = 0;
  for (const chunk of chunks) {
    const row = await database.getFirstAsync<{
      completed_count: number;
      verified_bytes: number;
    }>(
      `SELECT
         SUM(CASE WHEN state = 'completed' THEN 1 ELSE 0 END) AS completed_count,
         COALESCE(SUM(CASE WHEN state = 'completed' THEN verified_plaintext_bytes ELSE 0 END), 0)
           AS verified_bytes
       FROM my_photos_downloads
       WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
         AND quality = ? AND state != 'removed'
         AND media_asset_id IN (${chunk.map(() => '?').join(',')})`,
      context.namespace,
      context.tripId,
      context.passengerId,
      quality,
      ...chunk,
    );
    completedItemCount += row?.completed_count ?? 0;
    verifiedPlaintextBytes += row?.verified_bytes ?? 0;
  }
  if (!Number.isSafeInteger(completedItemCount) || !Number.isSafeInteger(verifiedPlaintextBytes)) {
    throw new Error('Photo retained progress overflowed.');
  }
  return { completedItemCount, verifiedPlaintextBytes };
}

type PhotoDownloadEnqueueRequest = Readonly<{
  assetId: string;
  quality: DownloadQuality;
  deliveryVersion: number;
}>;

async function enqueuePhotoDownloadsInTransaction(
  transaction: SQLite.SQLiteDatabase,
  context: MyPhotosContext,
  requests: readonly PhotoDownloadEnqueueRequest[],
  options: Readonly<{ batchId?: string | null; wifiOnly?: boolean }>,
  nowIso: string,
): Promise<number> {
  const coalesced = coalescePhotoDownloadRequests(requests);
  if (coalesced.length > 10_000) throw new Error('Download selection exceeds the local queue limit.');
  const versions = new Map(requests.map((request) => [
    `${request.assetId}:${request.quality}`,
    request.deliveryVersion,
  ]));
  let added = 0;
  for (const request of coalesced) {
    const version = versions.get(`${request.assetId}:${request.quality}`);
    if (!Number.isSafeInteger(version) || (version ?? -1) < 0) {
      throw new Error('Download delivery version is invalid.');
    }
    const result = await transaction.runAsync(
      `INSERT INTO my_photos_downloads
          (id, batch_id, account_namespace, trip_id, passenger_id, media_asset_id,
           quality, wifi_only, state, delivery_version, expected_size_bytes,
           expected_checksum_sha256, content_type, verified_plaintext_bytes,
           encrypted_size_bytes, encrypted_file_uri, attempt_count, preparation_poll_count,
           integrity_verified_at, next_attempt_at, stable_error_code,
           authorization_expires_at, supports_ranges, created_at, updated_at, completed_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, NULL, NULL, NULL, 0,
                 NULL, NULL, 0, 0, NULL, NULL, NULL, NULL, 0, ?, ?, NULL)
         ON CONFLICT DO NOTHING`,
      randomUUID(),
      options.batchId ?? null,
      context.namespace,
      context.tripId,
      context.passengerId,
      request.assetId,
      request.quality,
      options.wifiOnly ? 1 : 0,
      version!,
      nowIso,
      nowIso,
    );
    added += result.changes;
  }
  return added;
}

export async function enqueuePhotoDownloads(
  context: MyPhotosContext,
  requests: readonly PhotoDownloadEnqueueRequest[],
  options: Readonly<{ batchId?: string | null; wifiOnly?: boolean }> = {},
  nowIso = new Date().toISOString(),
): Promise<number> {
  const database = await openAccountDatabase(context.namespace);
  let added = 0;
  await withAccountTransaction(database, async (transaction) => {
    added = await enqueuePhotoDownloadsInTransaction(
      transaction,
      context,
      requests,
      options,
      nowIso,
    );
  });
  return added;
}

export async function enqueueAndCheckpointDownloadAllPage(
  context: MyPhotosContext,
  batch: Pick<PhotoDownloadBatch, 'id' | 'quality' | 'wifiOnly'>,
  assetIds: readonly string[],
  checkpoint: Readonly<{
    filter: PhotoDownloadBatch['checkpointFilter'];
    cursor: string | null;
  }>,
  nowIso = new Date().toISOString(),
): Promise<number> {
  const database = await openAccountDatabase(context.namespace);
  let added = 0;
  await withAccountTransaction(database, async (transaction) => {
    added = await enqueuePhotoDownloadsInTransaction(
      transaction,
      context,
      assetIds.map((assetId) => ({ assetId, quality: batch.quality, deliveryVersion: 0 })),
      { batchId: batch.id, wifiOnly: batch.wifiOnly },
      nowIso,
    );
    const result = await transaction.runAsync(
      `UPDATE my_photos_download_batches
          SET checkpoint_filter = ?, cursor = ?, enqueued_count = enqueued_count + ?,
              enumerated_count = enumerated_count + ?, updated_at = ?
        WHERE id = ? AND account_namespace = ? AND trip_id = ? AND passenger_id = ?
          AND request_kind IN ('all_matched', 'filter_selection') AND state = 'active'`,
      checkpoint.filter,
      checkpoint.cursor,
      added,
      assetIds.length,
      nowIso,
      batch.id,
      context.namespace,
      context.tripId,
      context.passengerId,
    );
    if (result.changes !== 1) throw new Error('Download-all batch changed before its page committed.');
  });
  return added;
}

export async function beginDownloadAllBatch(
  context: MyPhotosContext,
  quality: DownloadQuality,
  wifiOnly: boolean,
  galleryRevision: number,
  expectedItemCount: number,
  nowIso = new Date().toISOString(),
): Promise<Readonly<{ batch: PhotoDownloadBatch; created: boolean }>> {
  if (
    !Number.isSafeInteger(galleryRevision)
    || galleryRevision < 1
    || !Number.isSafeInteger(expectedItemCount)
    || expectedItemCount < 1
  ) {
    throw new Error('Download-all gallery revision is invalid.');
  }
  const database = await openAccountDatabase(context.namespace);
  const id = randomUUID();
  let created = false;
  await withAccountTransaction(database, async (transaction) => {
    const result = await transaction.runAsync(
      `INSERT INTO my_photos_download_batches
        (id, account_namespace, trip_id, passenger_id, request_kind, quality, state,
         wifi_only, estimated_bytes, checkpoint_filter, enqueued_count, enumerated_count,
         expected_item_count, selection_filter, excluded_asset_ids_json, cursor,
         gallery_revision, created_at, updated_at)
       VALUES (?, ?, ?, ?, 'all_matched', ?, 'active', ?, NULL, 'best', 0, 0,
               ?, NULL, '[]', NULL, ?, ?, ?)
       ON CONFLICT DO NOTHING`,
      id,
      context.namespace,
      context.tripId,
      context.passengerId,
      quality,
      wifiOnly ? 1 : 0,
      expectedItemCount,
      galleryRevision,
      nowIso,
      nowIso,
    );
    created = result.changes === 1;
  });
  const row = await database.getFirstAsync<{
    id: string;
    checkpoint_filter: PhotoDownloadBatch['checkpointFilter'];
    cursor: string | null;
    enqueued_count: number;
    enumerated_count: number;
    expected_item_count: number;
    quality: DownloadQuality;
    wifi_only: number;
    gallery_revision: number;
    state: PhotoDownloadBatch['state'];
  }>(
    `SELECT id, checkpoint_filter, cursor, enqueued_count, enumerated_count,
            expected_item_count, quality, wifi_only,
            gallery_revision, state
       FROM my_photos_download_batches
      WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
        AND request_kind = 'all_matched' AND quality = ? AND gallery_revision = ?
        AND state IN ('active', 'paused')
      ORDER BY created_at ASC LIMIT 1`,
    context.namespace,
    context.tripId,
    context.passengerId,
    quality,
    galleryRevision,
  );
  if (!row) throw new Error('Download-all batch could not be created.');
  return {
    created,
    batch: {
      id: row.id,
      requestKind: 'all_matched',
      checkpointFilter: row.checkpoint_filter,
      selectionFilter: null,
      excludedAssetIds: [],
      cursor: row.cursor,
      enqueuedCount: row.enqueued_count,
      enumeratedCount: row.enumerated_count,
      expectedItemCount: row.expected_item_count,
      quality: row.quality,
      wifiOnly: Boolean(row.wifi_only),
      galleryRevision: row.gallery_revision,
      state: row.state,
    },
  };
}

function normalizeExcludedPhotoIds(assetIds: readonly string[]): readonly string[] {
  const values = [...new Set(assetIds)].sort();
  if (
    values.length > 500
    || values.some((id) => !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(id))
  ) throw new Error('Filter selection exclusions are invalid.');
  return values;
}

function parseExcludedPhotoIds(serialized: string): readonly string[] {
  const value: unknown = JSON.parse(serialized);
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string')) {
    throw new Error('Filter selection exclusions are corrupt.');
  }
  return normalizeExcludedPhotoIds(value);
}

export async function beginFilterSelectionBatch(
  context: MyPhotosContext,
  quality: DownloadQuality,
  wifiOnly: boolean,
  galleryRevision: number,
  filter: 'best' | 'possible',
  expectedItemCount: number,
  excludedAssetIds: readonly string[],
  nowIso = new Date().toISOString(),
): Promise<Readonly<{ batch: PhotoDownloadBatch; created: boolean }>> {
  if (
    !Number.isSafeInteger(galleryRevision)
    || galleryRevision < 1
    || !Number.isSafeInteger(expectedItemCount)
    || expectedItemCount < 1
  ) throw new Error('Filter download batch identity is invalid.');
  const exclusions = normalizeExcludedPhotoIds(excludedAssetIds);
  const exclusionsJson = JSON.stringify(exclusions);
  const database = await openAccountDatabase(context.namespace);
  const id = randomUUID();
  const result = await database.runAsync(
    `INSERT INTO my_photos_download_batches
      (id, account_namespace, trip_id, passenger_id, request_kind, quality, state,
       wifi_only, estimated_bytes, checkpoint_filter, enqueued_count, enumerated_count,
       expected_item_count, selection_filter, excluded_asset_ids_json, cursor,
       gallery_revision, created_at, updated_at)
     VALUES (?, ?, ?, ?, 'filter_selection', ?, 'active', ?, NULL, ?, 0, 0,
             ?, ?, ?, NULL, ?, ?, ?)
     ON CONFLICT DO NOTHING`,
    id,
    context.namespace,
    context.tripId,
    context.passengerId,
    quality,
    wifiOnly ? 1 : 0,
    filter,
    expectedItemCount,
    filter,
    exclusionsJson,
    galleryRevision,
    nowIso,
    nowIso,
  );
  const row = await database.getFirstAsync<{
    id: string;
    checkpoint_filter: PhotoDownloadBatch['checkpointFilter'];
    selection_filter: 'best' | 'possible';
    excluded_asset_ids_json: string;
    cursor: string | null;
    enqueued_count: number;
    enumerated_count: number;
    expected_item_count: number;
    quality: DownloadQuality;
    wifi_only: number;
    gallery_revision: number;
    state: PhotoDownloadBatch['state'];
  }>(
    `SELECT id, checkpoint_filter, selection_filter, excluded_asset_ids_json,
            cursor, enqueued_count, enumerated_count, expected_item_count,
            quality, wifi_only, gallery_revision, state
       FROM my_photos_download_batches
      WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
        AND request_kind = 'filter_selection' AND quality = ? AND selection_filter = ?
        AND excluded_asset_ids_json = ? AND gallery_revision = ?
        AND state IN ('active', 'paused')
      ORDER BY created_at ASC LIMIT 1`,
    context.namespace,
    context.tripId,
    context.passengerId,
    quality,
    filter,
    exclusionsJson,
    galleryRevision,
  );
  if (!row) throw new Error('Filter download batch could not be created.');
  return {
    created: result.changes === 1,
    batch: {
      id: row.id,
      requestKind: 'filter_selection',
      checkpointFilter: row.checkpoint_filter,
      selectionFilter: row.selection_filter,
      excludedAssetIds: parseExcludedPhotoIds(row.excluded_asset_ids_json),
      cursor: row.cursor,
      enqueuedCount: row.enqueued_count,
      enumeratedCount: row.enumerated_count,
      expectedItemCount: row.expected_item_count,
      quality: row.quality,
      wifiOnly: Boolean(row.wifi_only),
      galleryRevision: row.gallery_revision,
      state: row.state,
    },
  };
}

export async function checkpointDownloadAllBatch(
  context: MyPhotosContext,
  batchId: string,
  checkpoint: Readonly<{
    filter: PhotoDownloadBatch['checkpointFilter'];
    cursor: string | null;
    addedCount: number;
  }>,
): Promise<void> {
  if (!Number.isSafeInteger(checkpoint.addedCount) || checkpoint.addedCount < 0) {
    throw new Error('Download-all checkpoint count is invalid.');
  }
  const database = await openAccountDatabase(context.namespace);
  const result = await database.runAsync(
    `UPDATE my_photos_download_batches
        SET checkpoint_filter = ?, cursor = ?, enqueued_count = enqueued_count + ?, updated_at = ?
      WHERE id = ? AND account_namespace = ? AND trip_id = ? AND passenger_id = ? AND state = 'active'`,
    checkpoint.filter,
    checkpoint.cursor,
    checkpoint.addedCount,
    new Date().toISOString(),
    batchId,
    context.namespace,
    context.tripId,
    context.passengerId,
  );
  if (result.changes !== 1) throw new Error('Download-all batch changed before checkpoint commit.');
}

export async function setDownloadAllBatchState(
  context: MyPhotosContext,
  batchId: string,
  state: 'active' | 'paused' | 'completed' | 'cancelled' | 'failed',
): Promise<void> {
  const database = await openAccountDatabase(context.namespace);
  const result = await database.runAsync(
    `UPDATE my_photos_download_batches
        SET state = ?, updated_at = ?
      WHERE id = ? AND account_namespace = ? AND trip_id = ? AND passenger_id = ?
        AND request_kind IN ('all_matched', 'filter_selection')`,
    state,
    new Date().toISOString(),
    batchId,
    context.namespace,
    context.tripId,
    context.passengerId,
  );
  if (result.changes !== 1) throw new Error('Download-all batch was not found in this account.');
}

export async function listUnfinishedDownloadAllBatches(
  context: MyPhotosContext,
): Promise<readonly PhotoDownloadBatch[]> {
  const database = await openAccountDatabase(context.namespace);
  const rows = await database.getAllAsync<{
    id: string;
    request_kind: PhotoDownloadBatch['requestKind'];
    checkpoint_filter: PhotoDownloadBatch['checkpointFilter'];
    selection_filter: PhotoDownloadBatch['selectionFilter'];
    excluded_asset_ids_json: string;
    cursor: string | null;
    enqueued_count: number;
    enumerated_count: number;
    expected_item_count: number;
    quality: DownloadQuality;
    wifi_only: number;
    gallery_revision: number;
    state: PhotoDownloadBatch['state'];
  }>(
    `SELECT id, request_kind, checkpoint_filter, selection_filter,
            excluded_asset_ids_json, cursor, enqueued_count, enumerated_count,
            expected_item_count, quality, wifi_only, gallery_revision, state
       FROM my_photos_download_batches
      WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
        AND request_kind IN ('all_matched', 'filter_selection') AND state IN ('active', 'paused')
      ORDER BY created_at ASC
      LIMIT 10`,
    context.namespace,
    context.tripId,
    context.passengerId,
  );
  return rows.map((row) => ({
    id: row.id,
    requestKind: row.request_kind,
    checkpointFilter: row.checkpoint_filter,
    selectionFilter: row.selection_filter,
    excludedAssetIds: parseExcludedPhotoIds(row.excluded_asset_ids_json),
    cursor: row.cursor,
    enqueuedCount: row.enqueued_count,
    enumeratedCount: row.enumerated_count,
    expectedItemCount: row.expected_item_count,
    quality: row.quality,
    wifiOnly: Boolean(row.wifi_only),
    galleryRevision: row.gallery_revision,
    state: row.state,
  }));
}

export async function cancelPhotoDownloadBatches(context: MyPhotosContext): Promise<number> {
  const database = await openAccountDatabase(context.namespace);
  const result = await database.runAsync(
    `UPDATE my_photos_download_batches
        SET state = 'cancelled', updated_at = ?
      WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
        AND state IN ('active', 'paused')`,
    new Date().toISOString(),
    context.namespace,
    context.tripId,
    context.passengerId,
  );
  return result.changes;
}

export async function recoverPhotoDownloadQueue(
  context: MyPhotosContext,
  network: Readonly<{ connected: boolean; wifi: boolean }>,
  nowIso = new Date().toISOString(),
): Promise<number> {
  const database = await openAccountDatabase(context.namespace);
  let interruptedCount = 0;
  await withAccountTransaction(database, async (transaction) => {
    const interrupted = await transaction.runAsync(
      `UPDATE my_photos_downloads
          SET state = 'retrying', stable_error_code = 'PROCESS_INTERRUPTED',
              next_attempt_at = ?, updated_at = ?
        WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ? AND state = 'downloading'`,
      nowIso,
      nowIso,
      context.namespace,
      context.tripId,
      context.passengerId,
    );
    interruptedCount = interrupted.changes;
    if (network.connected) {
      await transaction.runAsync(
        `UPDATE my_photos_downloads
            SET state = 'queued', stable_error_code = NULL, next_attempt_at = NULL, updated_at = ?
          WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
            AND state = 'paused' AND stable_error_code IN ('NETWORK_INTERRUPTED', 'APP_BACKGROUND')`,
        nowIso,
        context.namespace,
        context.tripId,
        context.passengerId,
      );
    }
    if (network.wifi) {
      await transaction.runAsync(
        `UPDATE my_photos_downloads
            SET state = 'queued', stable_error_code = NULL, next_attempt_at = NULL, updated_at = ?
          WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ? AND state = 'waiting_wifi'`,
        nowIso,
        context.namespace,
        context.tripId,
        context.passengerId,
      );
    }
  });
  return interruptedCount;
}

export async function nextPhotoDownloadWakeAt(
  context: MyPhotosContext,
): Promise<string | null> {
  const database = await openAccountDatabase(context.namespace);
  const row = await database.getFirstAsync<{ wake_at: string | null }>(
    `SELECT MIN(next_attempt_at) AS wake_at
       FROM my_photos_downloads
      WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
        AND state IN ('retrying', 'waiting_media_preparation')
        AND next_attempt_at IS NOT NULL`,
    context.namespace,
    context.tripId,
    context.passengerId,
  );
  return row?.wake_at ?? null;
}

export async function updatePhotoDownloadProgress(
  context: MyPhotosContext,
  id: string,
  verifiedPlaintextBytes: number,
  nowIso = new Date().toISOString(),
): Promise<void> {
  if (!Number.isSafeInteger(verifiedPlaintextBytes) || verifiedPlaintextBytes < 0) {
    throw new Error('Photo download progress is invalid.');
  }
  const database = await openAccountDatabase(context.namespace);
  const result = await database.runAsync(
    `UPDATE my_photos_downloads
        SET verified_plaintext_bytes = MAX(verified_plaintext_bytes, ?), updated_at = ?
      WHERE id = ? AND account_namespace = ? AND trip_id = ? AND passenger_id = ?
        AND state = 'downloading' AND expected_size_bytes IS NOT NULL
        AND ? <= expected_size_bytes`,
    verifiedPlaintextBytes,
    nowIso,
    id,
    context.namespace,
    context.tripId,
    context.passengerId,
    verifiedPlaintextBytes,
  );
  if (result.changes !== 1) {
    throw new Error('Photo download changed before progress committed.');
  }
}

export async function transitionPhotoDownload(
  context: MyPhotosContext,
  id: string,
  next: PhotoDownloadState,
  options: Readonly<{
    expectedCurrent?: readonly PhotoDownloadState[];
    errorCode?: string | null;
    nextAttemptAt?: string | null;
  }> = {},
  nowIso = new Date().toISOString(),
): Promise<PhotoDownloadJob> {
  const database = await openAccountDatabase(context.namespace);
  const current = await getOwnedJob(database, context, id);
  if (!current) throw new Error('Photo download was not found in this account.');
  if (options.expectedCurrent && !options.expectedCurrent.includes(current.state)) {
    throw new Error('Photo download changed before the requested transition.');
  }
  assertPhotoDownloadTransition(current.state, next);
  const result = await database.runAsync(
    `UPDATE my_photos_downloads
        SET state = ?, stable_error_code = ?, next_attempt_at = ?, updated_at = ?
      WHERE id = ? AND account_namespace = ? AND trip_id = ? AND passenger_id = ? AND state = ?`,
    next,
    options.errorCode ?? null,
    options.nextAttemptAt ?? null,
    nowIso,
    id,
    context.namespace,
    context.tripId,
    context.passengerId,
    current.state,
  );
  if (result.changes !== 1) throw new Error('Photo download changed before the transition committed.');
  return (await getOwnedJob(database, context, id))!;
}

export async function pauseActivePhotoTransfers(
  context: MyPhotosContext,
  reason: 'APP_BACKGROUND' | 'LOGOUT' | 'NETWORK_INTERRUPTED',
): Promise<number> {
  const database = await openAccountDatabase(context.namespace);
  const result = await database.runAsync(
    `UPDATE my_photos_downloads
        SET state = 'paused', stable_error_code = ?, next_attempt_at = NULL, updated_at = ?
      WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
        AND state = 'downloading'`,
    reason,
    new Date().toISOString(),
    context.namespace,
    context.tripId,
    context.passengerId,
  );
  return result.changes;
}

export async function markPhotoDownloadRemovalRequested(
  context: MyPhotosContext,
  id: string,
): Promise<PhotoDownloadJob> {
  const database = await openAccountDatabase(context.namespace);
  const current = await getOwnedJob(database, context, id);
  if (!current) throw new Error('Photo download was not found in this account.');
  const result = await database.runAsync(
    `UPDATE my_photos_downloads
        SET stable_error_code = 'REMOVAL_REQUESTED', updated_at = ?
      WHERE id = ? AND account_namespace = ? AND trip_id = ? AND passenger_id = ? AND state = ?`,
    new Date().toISOString(),
    id,
    context.namespace,
    context.tripId,
    context.passengerId,
    current.state,
  );
  if (result.changes !== 1) throw new Error('Photo removal intent changed before it committed.');
  return (await getOwnedJob(database, context, id))!;
}

export async function claimNextPhotoDownload(
  context: MyPhotosContext,
  network: Readonly<{ connected: boolean; wifi: boolean }>,
  nowIso = new Date().toISOString(),
): Promise<PhotoDownloadJob | null> {
  const database = await openAccountDatabase(context.namespace);
  let claimedId: string | null = null;
  await withAccountTransaction(database, async (transaction) => {
    const candidate = await transaction.getFirstAsync<PhotoDownloadRow>(
      `${PHOTO_DOWNLOAD_JOB_SELECT}
        WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
          AND state IN ('queued', 'retrying', 'expired_authorization', 'waiting_media_preparation')
          AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
        ORDER BY created_at ASC
        LIMIT 1`,
      context.namespace,
      context.tripId,
      context.passengerId,
      nowIso,
    );
    if (!candidate) return;
    const next: PhotoDownloadState = !network.connected
      ? 'paused'
      : candidate.wifi_only && !network.wifi
        ? 'waiting_wifi'
        : 'downloading';
    assertPhotoDownloadTransition(candidate.state, next);
    const increments = photoDownloadClaimCounterIncrements(candidate.state, next);
    const result = await transaction.runAsync(
      `UPDATE my_photos_downloads
          SET state = ?, attempt_count = attempt_count + ?,
              preparation_poll_count = preparation_poll_count + ?, next_attempt_at = NULL,
              stable_error_code = ?, updated_at = ?
        WHERE id = ? AND account_namespace = ? AND trip_id = ? AND passenger_id = ? AND state = ?`,
      next,
      increments.transferAttempts,
      increments.preparationPolls,
      next === 'paused' ? 'NETWORK_INTERRUPTED' : null,
      nowIso,
      candidate.id,
      context.namespace,
      context.tripId,
      context.passengerId,
      candidate.state,
    );
    if (result.changes === 1 && next === 'downloading') claimedId = candidate.id;
  });
  return claimedId ? getOwnedJob(database, context, claimedId) : null;
}

export async function registerCompletedPhotoDownload(
  context: MyPhotosContext,
  job: PhotoDownloadJob,
  file: Readonly<{
    uri: string;
    encryptedBytes: number;
    plaintextBytes: number;
    checksumSha256: string;
    contentType: NonNullable<PhotoDownloadJob['contentType']>;
  }>,
  nowIso = new Date().toISOString(),
): Promise<PhotoDownloadJob> {
  if (job.state !== 'downloading') throw new Error('Only an active transfer can complete.');
  if (!file.uri.startsWith('file:///') || file.plaintextBytes < 1 || file.encryptedBytes < 29) {
    throw new Error('Completed encrypted photo metadata is invalid.');
  }
  if (
    job.expectedSizeBytes !== file.plaintextBytes
    || job.expectedChecksumSha256 !== file.checksumSha256
    || job.contentType !== file.contentType
  ) throw new Error('Completed photo did not match its authorized manifest metadata.');
  await assertCanonicalPhotoVaultUri({
    namespace: context.namespace,
    tripId: context.tripId,
    passengerId: context.passengerId,
    assetId: job.assetId,
    quality: job.quality,
    deliveryVersion: job.deliveryVersion,
    checksumSha256: file.checksumSha256,
    expectedSizeBytes: file.plaintextBytes,
    contentType: file.contentType,
  }, file.uri);
  const database = await openAccountDatabase(context.namespace);
  const result = await database.runAsync(
    `UPDATE my_photos_downloads
        SET state = 'completed', expected_size_bytes = ?, expected_checksum_sha256 = ?,
            content_type = ?, verified_plaintext_bytes = ?, encrypted_size_bytes = ?, encrypted_file_uri = ?,
            integrity_verified_at = ?, stable_error_code = NULL, next_attempt_at = NULL,
            updated_at = ?, completed_at = ?
      WHERE id = ? AND account_namespace = ? AND trip_id = ? AND passenger_id = ?
        AND state = 'downloading'`,
    file.plaintextBytes,
    file.checksumSha256,
    file.contentType,
    file.plaintextBytes,
    file.encryptedBytes,
    file.uri,
    nowIso,
    nowIso,
    nowIso,
    job.id,
    context.namespace,
    context.tripId,
    context.passengerId,
  );
  if (result.changes !== 1) throw new Error('Photo download changed before completion committed.');
  return (await getOwnedJob(database, context, job.id))!;
}

export async function markPhotoDownloadIntegrityVerified(
  context: MyPhotosContext,
  id: string,
  nowIso = new Date().toISOString(),
): Promise<void> {
  const database = await openAccountDatabase(context.namespace);
  const result = await database.runAsync(
    `UPDATE my_photos_downloads
        SET integrity_verified_at = ?, updated_at = ?
      WHERE id = ? AND account_namespace = ? AND trip_id = ? AND passenger_id = ?
        AND state = 'completed'`,
    nowIso,
    nowIso,
    id,
    context.namespace,
    context.tripId,
    context.passengerId,
  );
  if (result.changes !== 1) throw new Error('Photo changed before integrity verification committed.');
}

export async function updatePhotoDownloadAuthorizationMetadata(
  context: MyPhotosContext,
  job: PhotoDownloadJob,
  metadata: Readonly<{
    deliveryVersion: number;
    expectedSizeBytes: number;
    checksumSha256: string;
    contentType: NonNullable<PhotoDownloadJob['contentType']>;
    expiresAt: string;
    supportsRanges: boolean;
  }>,
): Promise<PhotoDownloadJob> {
  const database = await openAccountDatabase(context.namespace);
  const result = await database.runAsync(
    `UPDATE my_photos_downloads
        SET verified_plaintext_bytes = CASE
              WHEN delivery_version = ? AND expected_size_bytes = ?
               AND expected_checksum_sha256 = ? AND content_type = ?
              THEN verified_plaintext_bytes ELSE 0 END,
            delivery_version = ?, expected_size_bytes = ?, expected_checksum_sha256 = ?, content_type = ?,
            authorization_expires_at = ?, supports_ranges = ?, updated_at = ?
      WHERE id = ? AND account_namespace = ? AND trip_id = ? AND passenger_id = ?
        AND state = 'downloading'`,
    metadata.deliveryVersion,
    metadata.expectedSizeBytes,
    metadata.checksumSha256,
    metadata.contentType,
    metadata.deliveryVersion,
    metadata.expectedSizeBytes,
    metadata.checksumSha256,
    metadata.contentType,
    metadata.expiresAt,
    metadata.supportsRanges ? 1 : 0,
    new Date().toISOString(),
    job.id,
    context.namespace,
    context.tripId,
    context.passengerId,
  );
  if (result.changes !== 1) throw new Error('Photo authorization changed before it committed.');
  return (await getOwnedJob(database, context, job.id))!;
}

export async function photoDownloadStorageSummary(context: MyPhotosContext): Promise<Readonly<{
  completedCount: number;
  encryptedBytes: number;
  activeCount: number;
}>> {
  const database = await openAccountDatabase(context.namespace);
  const row = await database.getFirstAsync<{
    completed_count: number;
    encrypted_bytes: number;
    active_count: number;
  }>(
    `SELECT
       SUM(CASE WHEN state = 'completed' THEN 1 ELSE 0 END) AS completed_count,
       SUM(CASE WHEN state = 'completed' THEN encrypted_size_bytes ELSE 0 END) AS encrypted_bytes,
       SUM(CASE WHEN state IN ('queued', 'waiting_wifi', 'waiting_media_preparation',
          'downloading', 'paused', 'retrying', 'expired_authorization') THEN 1 ELSE 0 END) AS active_count
       FROM my_photos_downloads
      WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ? AND state != 'removed'`,
    context.namespace,
    context.tripId,
    context.passengerId,
  );
  return {
    completedCount: row?.completed_count ?? 0,
    encryptedBytes: row?.encrypted_bytes ?? 0,
    activeCount: row?.active_count ?? 0,
  };
}

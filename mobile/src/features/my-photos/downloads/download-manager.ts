import { AbortableSharedTaskRegistry } from '@/core/async/abortable-shared-task';
import { ApiError } from '@/core/api/client';
import { recordMobileMetric } from '@/core/observability/mobile-observability';

import type {
  DownloadQuality,
  MyPhotosAsset,
  MyPhotosSummary,
} from '../api/contracts';
import {
  authorizeMyPhotosDownloads,
  getMyPhotosDownloadPlan,
  getMyPhotosPage,
  myPhotosDownloadContentPath,
  prepareMyPhotosAsset,
} from '../api/my-photos-api';
import { MY_PHOTOS_PAGE_SIZE } from '../data/gallery-window';
import {
  assertMyPhotosContextStillCurrent,
  myPhotosContextStillCurrent,
  runWhenMyPhotosContextCurrent,
  type MyPhotosContext,
} from '../data/my-photos-context';
import {
  beginDownloadAllBatch,
  beginFilterSelectionBatch,
  cancelPhotoDownloadBatches,
  claimNextPhotoDownload,
  checkpointPhotoDownloadReconciliation,
  enqueueAndCheckpointDownloadAllPage,
  enqueuePhotoDownloads,
  findPhotoDownload,
  getPhotoDownloadReconciliationCursor,
  getPhotoDownload,
  listPhotoDownloadManifestPage,
  listUnfinishedDownloadAllBatches,
  markPhotoDownloadRemovalRequested,
  markPhotoDownloadIntegrityVerified,
  pauseActivePhotoTransfers,
  photoDownloadRetainedProgress,
  photoDownloadStorageSummary,
  recoverPhotoDownloadQueue,
  registerCompletedPhotoDownload,
  setDownloadAllBatchState,
  transitionPhotoDownload,
  updatePhotoDownloadAuthorizationMetadata,
  updatePhotoDownloadProgress,
  type PhotoDownloadBatch,
  type PhotoDownloadJob,
  type PhotoDownloadManifestCursor,
} from './download-repository';
import {
  MY_PHOTOS_DOWNLOAD_CONCURRENCY,
  MY_PHOTOS_MAX_ACCOUNT_BYTES,
  MY_PHOTOS_MAX_APP_BYTES,
  MY_PHOTOS_MAX_ITEM_BYTES,
  MY_PHOTOS_MAX_RETRY_ATTEMPTS,
  photoDownloadRetryDelayMs,
  photoStorageActionIncludes,
  type PhotoDownloadState,
} from './download-policy';
import {
  assertPhotoDownloadPlanOwner,
  buildPhotoDownloadPlan,
  checkedPhotoDownloadSum,
  intersectPhotoDownloadQualities,
  plannedPhotoDownloadAsset,
  type PhotoDownloadPlan,
} from './photo-download-plan';
import { PhotoDownloadExecutionRegistry } from './photo-download-execution-registry';
import {
  MY_PHOTOS_RECONCILIATION_PAGE_SIZE,
  PhotoDownloadReconciliationBudget,
} from './photo-download-reconciliation-policy';
import {
  discardSupersededPhotoStaging,
  type PhotoDeliveryIdentity,
} from './photo-delivery-identity';
import {
  PhotoVaultIntegrityError,
  PhotoVaultStorageError,
  assertCanonicalPhotoVaultUri,
  availablePhotoVaultDiskBytes,
  decryptPhotoForViewing,
  discardPhotoVaultStaging,
  downloadPhotoToVault,
  inspectPhotoVaultFile,
  inspectPhotoVaultFileMetadata,
  photoVaultStorageUsage,
  purgePhotoTemporaryFiles,
  releasePhotoView,
  removePhotoVaultFile,
  type PhotoVaultInput,
} from './photo-vault';

const MAX_DOWNLOAD_ALL_PAGES_PER_FILTER = 256;
const RECENT_DOWNLOAD_ALL_CURSORS = 8;
const RUNTIME_DOWNLOAD_ALL_PAGE_BUDGET = 1;
const CORRUPT_FILE_REMOVAL_PENDING = 'CORRUPT_FILE_REMOVAL_PENDING';

export function isPhotoDownloadDeliveryFailureRetryable(error: unknown): boolean {
  return error instanceof TypeError
    || (error instanceof ApiError && (
      error.status === 0
      || error.status === 408
      || error.status === 429
      || error.status >= 500
    ));
}

export type { PhotoDownloadPlan } from './photo-download-plan';

export type PhotoDownloadActivation = Readonly<{
  kind: PhotoDownloadPlan['kind'];
  queuedCount: number;
  batchId: string | null;
}>;

export type PhotoDownloadNetwork = Readonly<{
  connected: boolean;
  wifi: boolean;
}>;

export type LocalPhotoLease = Readonly<{
  uri: string;
  mimeType: 'image/jpeg' | 'image/png' | 'image/webp';
  quality: DownloadQuality;
  jobId: string;
  release: () => void;
}>;

class PhotoDeliveryAdapterUnavailableError extends Error {
  constructor() {
    super('The configured photo delivery adapter is unavailable.');
    this.name = 'PhotoDeliveryAdapterUnavailableError';
  }
}

export const photoDownloadExecutions = new PhotoDownloadExecutionRegistry();
const downloadAllTasks = new AbortableSharedTaskRegistry<string, PhotoDownloadActivation>();

export async function planSelectedPhotoDownloads(
  context: MyPhotosContext,
  assets: readonly MyPhotosAsset[],
  galleryRevision: number,
): Promise<PhotoDownloadPlan> {
  const unique = new Map(assets.map((asset) => [asset.asset_id, asset]));
  const items = [...unique.values()].map(plannedPhotoDownloadAsset);
  if (!items.length) throw new Error('Select at least one photo to download.');
  const supported = intersectPhotoDownloadQualities(items);
  const originalBytes = checkedPhotoDownloadSum(items.map((item) => item.originalByteSize));
  const maximumItemBytes = Math.max(...items.map((item) => item.originalByteSize));
  const retainedEntries = await Promise.all(supported.map(async (quality) => [
    quality,
    await photoDownloadRetainedProgress(
      context,
      quality,
      items.map((item) => item.assetId),
    ),
  ] as const));
  return buildPhotoDownloadPlan(
    context,
    items.length === 1 ? 'one' : 'selected',
    galleryRevision,
    items.length,
    items,
    supported,
    Object.fromEntries(supported.map((quality) => [quality, originalBytes])),
    Object.fromEntries(supported.map((quality) => [quality, maximumItemBytes])),
    Object.fromEntries(supported.map((quality) => [
      quality,
      quality === 'original' ? 'exact' : 'conservative_upper_bound',
    ])),
    Object.fromEntries(retainedEntries),
  );
}

export async function planFilterPhotoDownloads(
  context: MyPhotosContext,
  summary: MyPhotosSummary,
  filter: 'best' | 'possible',
  excludedAssetIds: readonly string[],
  signal: AbortSignal = context.signal,
): Promise<PhotoDownloadPlan> {
  const exclusions = new Set(excludedAssetIds);
  if (exclusions.size !== excludedAssetIds.length || exclusions.size > 500) {
    throw new Error('Filter selection exclusions are invalid.');
  }
  let cursor: string | null = null;
  const recentCursors: string[] = [];
  const supported = new Set<DownloadQuality>(['original', 'optimized']);
  let itemCount = 0;
  let totalBytes = 0;
  let maximumItemBytes = 0;
  let excludedSeen = 0;
  let pages = 0;
  do {
    if (signal.aborted) throw signal.reason instanceof Error ? signal.reason : new Error('Filter selection cancelled.');
    pages += 1;
    if (pages > MAX_DOWNLOAD_ALL_PAGES_PER_FILTER) {
      throw new Error('Filter selection exceeded its bounded cursor budget.');
    }
    if (cursor && recentCursors.includes(cursor)) throw new Error('Filter selection received a repeated cursor.');
    const page = await getMyPhotosPage(context.tripId, filter, {
      cursor,
      limit: MY_PHOTOS_PAGE_SIZE,
      signal,
    });
    if (page.snapshot_revision !== summary.results.snapshot_revision || page.filter !== filter) {
      throw new Error('The gallery changed while estimating this filter selection.');
    }
    const expectedFilterCount = filter === 'best'
      ? summary.search?.best_match_count ?? 0
      : summary.search?.possible_match_count ?? 0;
    if (page.total_count !== expectedFilterCount) {
      throw new Error('The filter count changed while estimating this selection.');
    }
    for (const asset of page.items) {
      if (exclusions.has(asset.asset_id)) {
        excludedSeen += 1;
        continue;
      }
      itemCount += 1;
      totalBytes = checkedPhotoDownloadSum([totalBytes, asset.original_byte_size]);
      maximumItemBytes = Math.max(maximumItemBytes, asset.original_byte_size);
      for (const quality of [...supported]) {
        if (!asset.download_qualities.includes(quality)) supported.delete(quality);
      }
    }
    if (page.next_cursor && (page.next_cursor === cursor || recentCursors.includes(page.next_cursor))) {
      throw new Error('Filter selection received a cursor loop.');
    }
    if (cursor) {
      recentCursors.push(cursor);
      if (recentCursors.length > RECENT_DOWNLOAD_ALL_CURSORS) recentCursors.shift();
    }
    cursor = page.next_cursor;
  } while (cursor);
  if (excludedSeen !== exclusions.size) throw new Error('Filter selection exclusions are stale.');
  const expectedSelectedCount = (filter === 'best'
    ? summary.search?.best_match_count ?? 0
    : summary.search?.possible_match_count ?? 0) - exclusions.size;
  if (itemCount !== expectedSelectedCount) {
    throw new Error('The server selection count changed while the plan was built.');
  }
  if (itemCount < 1 || totalBytes < 1 || maximumItemBytes < 1) {
    throw new Error('Select at least one photo to download.');
  }
  const qualities = [...supported];
  return buildPhotoDownloadPlan(
    context,
    'filter_selection',
    summary.results.snapshot_revision,
    itemCount,
    [],
    qualities,
    Object.fromEntries(qualities.map((quality) => [quality, totalBytes])),
    Object.fromEntries(qualities.map((quality) => [quality, maximumItemBytes])),
    Object.fromEntries(qualities.map((quality) => [
      quality,
      quality === 'original' ? 'exact' : 'conservative_upper_bound',
    ])),
    {},
    {
      filter,
      excludedAssetIds: Object.freeze([...exclusions].sort()),
    },
  );
}

export async function planAllMatchedPhotoDownloads(
  context: MyPhotosContext,
  summary: MyPhotosSummary,
): Promise<PhotoDownloadPlan> {
  const aggregate = await getMyPhotosDownloadPlan(context.tripId, context.signal);
  if (aggregate.snapshot_revision !== summary.results.snapshot_revision) {
    throw new Error('The gallery changed while estimating this download.');
  }
  if (aggregate.matched_item_count < 1) throw new Error('There are no matched photos to download.');
  const complete = aggregate.qualities.filter((quality) => (
    quality.estimate_complete
    && quality.supported_item_count === aggregate.matched_item_count
    && quality.exact_byte_total > 0
    && quality.maximum_item_bytes > 0
  ));
  const supported = complete.map((quality) => quality.quality);
  return buildPhotoDownloadPlan(
    context,
    'all_matched',
    summary.results.snapshot_revision,
    aggregate.matched_item_count,
    [],
    supported,
    Object.fromEntries(complete.map((quality) => [quality.quality, quality.exact_byte_total])),
    Object.fromEntries(complete.map((quality) => [quality.quality, quality.maximum_item_bytes])),
    Object.fromEntries(complete.map((quality) => [quality.quality, 'exact'])),
    // A trip-wide manifest may include assets superseded by this match
    // revision. Applying that unproven credit would understate required space;
    // queue coalescing still prevents already-current files from redownloading.
    {},
  );
}

async function ensureActivationFits(context: MyPhotosContext, plan: PhotoDownloadPlan, quality: DownloadQuality): Promise<void> {
  if (!plan.supportedQualities.includes(quality)) throw new Error('That quality is not available for every selected photo.');
  const estimate = plan.estimatedBytesByQuality[quality];
  const remaining = plan.remainingBytesByQuality[quality];
  const maximumItem = plan.maximumItemBytesByQuality[quality];
  const required = plan.requiredDeviceBytesByQuality[quality];
  const encryptedGrowth = plan.encryptedGrowthBytesByQuality[quality];
  const available = availablePhotoVaultDiskBytes();
  const usage = await photoVaultStorageUsage(context.namespace);
  if (
    !estimate
    || remaining === undefined
    || !maximumItem
    || required === undefined
    || encryptedGrowth === undefined
    || maximumItem > MY_PHOTOS_MAX_ITEM_BYTES
    || (remaining > 0 && available <= 0)
    || required > available
    || usage.accountBytes + encryptedGrowth > MY_PHOTOS_MAX_ACCOUNT_BYTES
    || usage.appBytes + encryptedGrowth > MY_PHOTOS_MAX_APP_BYTES
  ) throw new PhotoVaultStorageError();
}

export async function enumerateDownloadAll(
  context: MyPhotosContext,
  batch: PhotoDownloadBatch,
  signal: AbortSignal,
  activationPageBudget = MAX_DOWNLOAD_ALL_PAGES_PER_FILTER * 2,
): Promise<PhotoDownloadActivation> {
  if (
    !Number.isSafeInteger(activationPageBudget)
    || activationPageBudget < 1
    || activationPageBudget > MAX_DOWNLOAD_ALL_PAGES_PER_FILTER * 2
  ) throw new Error('Download All activation page budget is invalid.');
  if (batch.state === 'paused') await setDownloadAllBatchState(context, batch.id, 'active');
  let filter = batch.checkpointFilter;
  let cursor = batch.cursor;
  let addedTotal = 0;
  let enumeratedTotal = 0;
  let processedPages = 0;
  const exclusions = new Set(batch.excludedAssetIds);
  const recentCursors: string[] = [];
  try {
    while (filter) {
      const activeFilter: Exclude<PhotoDownloadBatch['checkpointFilter'], null> = filter;
      let pages = 0;
      while (true) {
        if (signal.aborted) throw signal.reason instanceof Error ? signal.reason : new Error('Download All interrupted.');
        pages += 1;
        if (pages > MAX_DOWNLOAD_ALL_PAGES_PER_FILTER) throw new Error('Download All exceeded its bounded page budget.');
        if (cursor && recentCursors.includes(cursor)) throw new Error('Download All received a repeated cursor.');
        const page = await getMyPhotosPage(context.tripId, activeFilter, {
          cursor,
          limit: MY_PHOTOS_PAGE_SIZE,
          signal,
        });
        if (page.snapshot_revision !== batch.galleryRevision || page.filter !== activeFilter) {
          throw new Error('The gallery changed while Download All was being queued.');
        }
        if (page.next_cursor && (page.next_cursor === cursor || recentCursors.includes(page.next_cursor))) {
          throw new Error('Download All received a cursor loop.');
        }
        if (cursor) {
          recentCursors.push(cursor);
          if (recentCursors.length > RECENT_DOWNLOAD_ALL_CURSORS) recentCursors.shift();
        }
        const nextFilter: PhotoDownloadBatch['checkpointFilter'] = page.next_cursor
          ? activeFilter
          : batch.requestKind === 'all_matched' && activeFilter === 'best'
            ? 'possible'
            : null;
        const nextCursor = page.next_cursor ?? null;
        const selectedAssets = page.items.filter((asset) => !exclusions.has(asset.asset_id));
        if (selectedAssets.some((asset) => !asset.download_qualities.includes(batch.quality))) {
          throw new Error('A planned photo no longer supports the selected download quality.');
        }
        if (batch.enumeratedCount + enumeratedTotal + selectedAssets.length > batch.expectedItemCount) {
          throw new Error('The server selection count changed before the batch completed.');
        }
        const added = await enqueueAndCheckpointDownloadAllPage(
          context,
          batch,
          selectedAssets.map((asset) => asset.asset_id),
          { filter: nextFilter, cursor: nextCursor },
        );
        addedTotal += added;
        enumeratedTotal += selectedAssets.length;
        processedPages += 1;
        if (nextFilter === null) {
          filter = null;
          cursor = null;
          if (batch.enumeratedCount + enumeratedTotal !== batch.expectedItemCount) {
            throw new Error('The server selection count changed before the batch completed.');
          }
          await setDownloadAllBatchState(context, batch.id, 'completed');
          break;
        }
        filter = nextFilter;
        cursor = nextCursor;
        // Runtime activations checkpoint only a small producer slice so the
        // consumer can begin transferring immediately instead of waiting for
        // an entire large catalog to be enumerated into SQLite.
        if (processedPages >= activationPageBudget) {
          return { kind: batch.requestKind, queuedCount: addedTotal, batchId: batch.id };
        }
        if (page.next_cursor) {
          continue;
        }
        break;
      }
    }
    return { kind: batch.requestKind, queuedCount: addedTotal, batchId: batch.id };
  } catch (error) {
    await setDownloadAllBatchState(
      context,
      batch.id,
      signal.aborted ? 'paused' : 'failed',
    ).catch(() => {
      recordMobileMetric('my_photos_download_event', 1, { my_photos_download_event: 'failed' });
    });
    throw error;
  }
}

export async function activatePhotoDownloadPlan(
  context: MyPhotosContext,
  plan: PhotoDownloadPlan,
  quality: DownloadQuality,
  wifiOnly: boolean,
  signal: AbortSignal = context.signal,
): Promise<PhotoDownloadActivation> {
  assertPhotoDownloadPlanOwner(context, plan);
  await ensureActivationFits(context, plan, quality);
  if (plan.kind === 'one' || plan.kind === 'selected') {
    const queuedCount = await enqueuePhotoDownloads(
      context,
      plan.items.map((item) => ({ assetId: item.assetId, quality, deliveryVersion: 0 })),
      { wifiOnly },
    );
    return { kind: plan.kind, queuedCount, batchId: null };
  }
  const result = plan.kind === 'filter_selection' && plan.filterSelection
    ? await beginFilterSelectionBatch(
        context,
        quality,
        wifiOnly,
        plan.galleryRevision,
        plan.filterSelection.filter,
        plan.itemCount,
        plan.filterSelection.excludedAssetIds,
      )
    : await beginDownloadAllBatch(
        context,
        quality,
        wifiOnly,
        plan.galleryRevision,
        plan.itemCount,
      );
  if (result.batch.galleryRevision !== plan.galleryRevision) {
    await setDownloadAllBatchState(context, result.batch.id, 'failed');
    throw new Error('A stale Download All batch must be replaced after refreshing the gallery.');
  }
  if (signal.aborted) throw signal.reason instanceof Error ? signal.reason : new Error('Download All cancelled.');
  return {
    kind: plan.kind,
    queuedCount: 0,
    batchId: result.batch.id,
  };
}

function vaultInput(job: PhotoDownloadJob): PhotoVaultInput | null {
  if (!job.expectedSizeBytes || !job.expectedChecksumSha256 || !job.contentType) return null;
  return {
    namespace: job.namespace,
    tripId: job.tripId,
    passengerId: job.passengerId,
    assetId: job.assetId,
    quality: job.quality,
    deliveryVersion: job.deliveryVersion,
    expectedSizeBytes: job.expectedSizeBytes,
    checksumSha256: job.expectedChecksumSha256,
    contentType: job.contentType,
  };
}

async function safeTransitionFromDownloading(
  context: MyPhotosContext,
  jobId: string,
  state: PhotoDownloadState,
  errorCode: string,
  nextAttemptAt: string | null = null,
): Promise<void> {
  if (!myPhotosContextStillCurrent(context)) return;
  const latest = await getPhotoDownload(context, jobId);
  if (!latest || latest.state !== 'downloading') return;
  await transitionPhotoDownload(context, jobId, state, {
    expectedCurrent: ['downloading'],
    errorCode,
    nextAttemptAt,
  });
}

async function processClaimedDownload(
  context: MyPhotosContext,
  job: PhotoDownloadJob,
  parentSignal: AbortSignal,
): Promise<void> {
  const signal = photoDownloadExecutions.begin(context, job.id, parentSignal);
  recordMobileMetric('my_photos_download_event', 1, { my_photos_download_event: 'started' });
  try {
    const response = await authorizeMyPhotosDownloads(
      context.tripId,
      [{ assetId: job.assetId, quality: job.quality }],
      signal,
      job.id,
    );
    const authorization = response.authorizations[0];
    if (
      !authorization
      || authorization.asset_id !== job.assetId
      || authorization.quality !== job.quality
      || response.authorizations.length !== 1
    ) throw new Error('Download authorization did not match the queued photo.');
    assertMyPhotosContextStillCurrent(context);
    if (authorization.state !== 'available') {
      const preparation = authorization.state === 'preparing'
        ? await prepareMyPhotosAsset(context.tripId, job.assetId, job.quality, signal, job.id)
        : null;
      const retrySeconds = preparation?.retry_after_seconds
        ?? authorization.retry_after_seconds
        ?? 60;
      assertMyPhotosContextStillCurrent(context);
      await safeTransitionFromDownloading(
        context,
        job.id,
        'waiting_media_preparation',
        'MEDIA_PREPARING',
        new Date(Date.now() + retrySeconds * 1_000).toISOString(),
      );
      return;
    }
    if (
      !authorization.authorization_id
      || !authorization.content_type
      || !authorization.expected_size_bytes
      || !authorization.checksum_sha256
      || !authorization.expires_at
    ) throw new PhotoDeliveryAdapterUnavailableError();
    const resourcePath = authorization.transport === 'development_fixture'
      ? authorization.resource_path
      : authorization.transport === 'direct_object_storage' && !authorization.resource_path
        ? myPhotosDownloadContentPath(context.tripId, authorization.authorization_id)
        : null;
    if (!resourcePath) throw new PhotoDeliveryAdapterUnavailableError();
    if (Date.parse(authorization.expires_at) <= Date.now()) {
      await safeTransitionFromDownloading(context, job.id, 'expired_authorization', 'DOWNLOAD_AUTH_EXPIRED');
      return;
    }
    const authorizationIdentity: PhotoDeliveryIdentity = {
      deliveryVersion: authorization.delivery_version,
      expectedSizeBytes: authorization.expected_size_bytes,
      checksumSha256: authorization.checksum_sha256,
      contentType: authorization.content_type,
    };
    const previousVaultInput = vaultInput(job);
    assertMyPhotosContextStillCurrent(context);
    await discardSupersededPhotoStaging(
      previousVaultInput ? {
        deliveryVersion: previousVaultInput.deliveryVersion,
        expectedSizeBytes: previousVaultInput.expectedSizeBytes,
        checksumSha256: previousVaultInput.checksumSha256,
        contentType: previousVaultInput.contentType,
      } : null,
      authorizationIdentity,
      async () => {
        if (!previousVaultInput) throw new Error('Superseded photo staging identity is missing.');
        await discardPhotoVaultStaging(previousVaultInput);
      },
    );
    assertMyPhotosContextStillCurrent(context);
    const authorizedJob = await updatePhotoDownloadAuthorizationMetadata(context, job, {
      ...authorizationIdentity,
      expiresAt: authorization.expires_at,
      supportsRanges: authorization.supports_ranges,
    });
    const downloaded = await downloadPhotoToVault({
      namespace: context.namespace,
      tripId: context.tripId,
      passengerId: context.passengerId,
      assetId: authorizedJob.assetId,
      quality: authorizedJob.quality,
      deliveryVersion: authorization.delivery_version,
      expectedSizeBytes: authorization.expected_size_bytes,
      checksumSha256: authorization.checksum_sha256,
      contentType: authorization.content_type,
      authorizationId: authorization.authorization_id,
      resourcePath,
      supportsRanges: authorization.supports_ranges,
    }, signal, (verifiedPlaintextBytes) => {
      if (signal.aborted) {
        throw signal.reason instanceof Error ? signal.reason : new Error('Photo download cancelled.');
      }
      assertMyPhotosContextStillCurrent(context);
      return updatePhotoDownloadProgress(context, authorizedJob.id, verifiedPlaintextBytes);
    });
    if (signal.aborted) {
      throw signal.reason instanceof Error ? signal.reason : new Error('Photo download cancelled.');
    }
    assertMyPhotosContextStillCurrent(context);
    await registerCompletedPhotoDownload(context, authorizedJob, {
      uri: downloaded.uri,
      encryptedBytes: downloaded.encryptedBytes,
      plaintextBytes: downloaded.plaintextBytes,
      checksumSha256: downloaded.checksumSha256,
      contentType: downloaded.contentType,
    });
    recordMobileMetric('my_photos_download_event', 1, { my_photos_download_event: 'completed' });
    recordMobileMetric('my_photos_download_bytes', downloaded.plaintextBytes, { outcome: 'success' });
    if (downloaded.resumed) recordMobileMetric('my_photos_resume_success', 1, { outcome: 'success' });
  } catch (error) {
    if (signal.aborted) {
      if (myPhotosContextStillCurrent(context)) {
        await safeTransitionFromDownloading(context, job.id, 'paused', 'APP_BACKGROUND');
      }
      recordMobileMetric('my_photos_download_event', 1, { my_photos_download_event: 'paused' });
      return;
    }
    if (error instanceof PhotoVaultIntegrityError) {
      await safeTransitionFromDownloading(context, job.id, 'corrupt', error.code);
      recordMobileMetric('my_photos_checksum_failure', 1, { outcome: 'failure' });
      recordMobileMetric('my_photos_download_event', 1, { my_photos_download_event: 'failed' });
      return;
    }
    if (error instanceof PhotoVaultStorageError) {
      await safeTransitionFromDownloading(context, job.id, 'failed', error.code);
      recordMobileMetric('my_photos_low_storage_cancellation', 1, { outcome: 'cancelled' });
      recordMobileMetric('my_photos_download_event', 1, { my_photos_download_event: 'failed' });
      return;
    }
    if (error instanceof ApiError && (
      error.code === 'DOWNLOAD_AUTH_EXPIRED'
      || error.status === 401
    )) {
      await safeTransitionFromDownloading(context, job.id, 'expired_authorization', 'DOWNLOAD_AUTH_EXPIRED');
      return;
    }
    const retryable = isPhotoDownloadDeliveryFailureRetryable(error);
    if (retryable && job.attemptCount < MY_PHOTOS_MAX_RETRY_ATTEMPTS) {
      const delay = error instanceof ApiError && error.retryAfterSeconds !== null
        ? Math.min(60_000, Math.max(1_000, error.retryAfterSeconds * 1_000))
        : photoDownloadRetryDelayMs(Math.max(1, job.attemptCount));
      await safeTransitionFromDownloading(
        context,
        job.id,
        'retrying',
        'TRANSIENT_DELIVERY_FAILURE',
        new Date(Date.now() + delay).toISOString(),
      );
    } else {
      await safeTransitionFromDownloading(
        context,
        job.id,
        'failed',
        error instanceof PhotoDeliveryAdapterUnavailableError
          ? 'DELIVERY_ADAPTER_UNAVAILABLE'
          : 'DELIVERY_FAILED',
      );
      recordMobileMetric('my_photos_download_event', 1, { my_photos_download_event: 'failed' });
    }
  } finally {
    photoDownloadExecutions.finish(context, job.id);
  }
}

export async function drainPhotoDownloadQueue(
  context: MyPhotosContext,
  network: PhotoDownloadNetwork,
  signal: AbortSignal,
): Promise<void> {
  const worker = async (): Promise<void> => {
    while (!signal.aborted) {
      const job = await claimNextPhotoDownload(context, network);
      if (!job) return;
      await processClaimedDownload(context, job, signal);
    }
  };
  await Promise.all(Array.from({ length: MY_PHOTOS_DOWNLOAD_CONCURRENCY }, () => worker()));
}

export async function recoverAndReconcilePhotoDownloads(
  context: MyPhotosContext,
  network: PhotoDownloadNetwork,
  signal?: AbortSignal,
): Promise<number> {
  await purgePhotoTemporaryFiles();
  const interrupted = await recoverPhotoDownloadQueue(context, network);
  let recovered = interrupted;
  let cursor = await getPhotoDownloadReconciliationCursor(context);
  const budget = new PhotoDownloadReconciliationBudget();
  while (budget.canReadPage()) {
    if (signal?.aborted) throw signal.reason instanceof Error ? signal.reason : new Error('Reconciliation cancelled.');
    assertMyPhotosContextStillCurrent(context);
    const page = await listPhotoDownloadManifestPage(
      context,
      cursor,
      MY_PHOTOS_RECONCILIATION_PAGE_SIZE,
    );
    budget.recordRows(page.items.length);
    for (const job of page.items) {
      if (signal?.aborted) throw signal.reason instanceof Error ? signal.reason : new Error('Reconciliation cancelled.');
      assertMyPhotosContextStillCurrent(context);
      if (job.stableErrorCode === 'REMOVAL_REQUESTED') {
        const input = vaultInput(job);
        try {
          if (input && job.encryptedFileUri) {
            await removePhotoVaultFile({ ...input, encryptedUri: job.encryptedFileUri });
          }
        } catch {
          recordMobileMetric('my_photos_download_event', 1, { my_photos_download_event: 'failed' });
          continue;
        }
        if (['completed', 'corrupt', 'failed', 'cancelled', 'paused'].includes(job.state)) {
          await transitionPhotoDownload(context, job.id, 'removed', { expectedCurrent: [job.state] });
          recovered += 1;
        }
        continue;
      }
      if (job.stableErrorCode === CORRUPT_FILE_REMOVAL_PENDING && job.state === 'corrupt') {
        const input = vaultInput(job);
        if (!input) continue;
        try {
          if (job.encryptedFileUri) {
            await removePhotoVaultFile({ ...input, encryptedUri: job.encryptedFileUri });
          }
          await discardPhotoVaultStaging(input);
          await transitionPhotoDownload(context, job.id, 'corrupt', {
            expectedCurrent: ['corrupt'],
            errorCode: 'LOCAL_FILE_CORRUPT',
          });
          recovered += 1;
        } catch {
          recordMobileMetric('my_photos_download_event', 1, { my_photos_download_event: 'failed' });
        }
        continue;
      }
      if (job.state === 'cancelled') {
        const input = vaultInput(job);
        if (input) {
          try {
            await discardPhotoVaultStaging(input);
          } catch {
            recordMobileMetric('my_photos_download_event', 1, { my_photos_download_event: 'failed' });
          }
        }
        continue;
      }
      if (job.state !== 'completed') continue;
      const input = vaultInput(job);
      if (!input || !job.encryptedFileUri || !job.encryptedSizeBytes) {
        await transitionPhotoDownload(context, job.id, 'corrupt', {
          expectedCurrent: ['completed'],
          errorCode: 'LOCAL_MANIFEST_INVALID',
        });
        recovered += 1;
        continue;
      }
      const metadataStatus = await inspectPhotoVaultFileMetadata({
        ...input,
        encryptedUri: job.encryptedFileUri,
        expectedEncryptedBytes: job.encryptedSizeBytes,
      });
      if (metadataStatus !== 'present') {
        await transitionPhotoDownload(context, job.id, 'corrupt', {
          expectedCurrent: ['completed'],
          errorCode: metadataStatus === 'missing' ? 'LOCAL_FILE_MISSING' : 'LOCAL_FILE_SIZE_MISMATCH',
        });
        recovered += 1;
        continue;
      }
      if (job.integrityVerifiedAt || !budget.claimFullInspection()) continue;
      const status = await inspectPhotoVaultFile({ ...input, encryptedUri: job.encryptedFileUri }, signal);
      if (status !== 'valid') {
        if (status === 'corrupt') {
          await transitionPhotoDownload(context, job.id, 'corrupt', {
            expectedCurrent: ['completed'],
            errorCode: 'REMOVAL_REQUESTED',
          });
          recordMobileMetric('my_photos_checksum_failure', 1, { outcome: 'failure' });
          try {
            await removePhotoVaultFile({ ...input, encryptedUri: job.encryptedFileUri });
            await transitionPhotoDownload(context, job.id, 'removed', { expectedCurrent: ['corrupt'] });
          } catch {
            recordMobileMetric('my_photos_download_event', 1, { my_photos_download_event: 'failed' });
          }
          recovered += 1;
          continue;
        }
        await transitionPhotoDownload(context, job.id, 'corrupt', {
          expectedCurrent: ['completed'],
          errorCode: status === 'missing' ? 'LOCAL_FILE_MISSING' : 'LOCAL_FILE_CORRUPT',
        });
        recovered += 1;
      } else {
        await markPhotoDownloadIntegrityVerified(context, job.id);
      }
    }
    cursor = page.nextCursor;
    await checkpointPhotoDownloadReconciliation(context, cursor);
    if (!cursor || page.items.length === 0) break;
  }
  if (recovered) {
    recordMobileMetric('my_photos_queue_recovery', recovered, { outcome: 'success', trigger: 'startup' });
    recordMobileMetric('my_photos_download_event', recovered, { my_photos_download_event: 'recovered' });
  }
  return recovered;
}

export async function resumeUnfinishedDownloadAll(
  context: MyPhotosContext,
  signal: AbortSignal,
): Promise<boolean> {
  const batches = await listUnfinishedDownloadAllBatches(context);
  const batch = batches[0];
  if (!batch || signal.aborted) return false;
  const key = `${context.namespace}|${context.tripId}|${context.passengerId}|${batch.id}`;
  await downloadAllTasks.run(
    key,
    (sharedSignal) => enumerateDownloadAll(
      context,
      batch,
      AbortSignal.any([sharedSignal, context.signal]),
      RUNTIME_DOWNLOAD_ALL_PAGE_BUDGET,
    ),
    signal,
  );
  // The caller schedules another bounded producer activation. This may cause
  // one harmless final no-op activation when this page completed the batch,
  // but it avoids a second database read on the latency-critical path.
  return true;
}

export async function pausePhotoDownload(context: MyPhotosContext, id: string): Promise<void> {
  await photoDownloadExecutions.abortAndWait(context, id, new Error('Photo download paused.'));
  const job = await getPhotoDownload(context, id);
  if (!job || job.state === 'paused') return;
  if (['queued', 'waiting_wifi', 'waiting_media_preparation', 'downloading', 'retrying', 'expired_authorization'].includes(job.state)) {
    await transitionPhotoDownload(context, id, 'paused', {
      expectedCurrent: [job.state],
      errorCode: 'USER_PAUSED',
    });
    recordMobileMetric('my_photos_download_event', 1, { my_photos_download_event: 'paused' });
  }
}

export async function pausePhotoDownloadsForLifecycle(
  context: MyPhotosContext,
  reason: 'APP_BACKGROUND' | 'NETWORK_INTERRUPTED',
): Promise<number> {
  await photoDownloadExecutions.abortContextAndWait(context, new Error(reason));
  const pause = runWhenMyPhotosContextCurrent(
    context,
    () => pauseActivePhotoTransfers(context, reason),
  );
  const paused = pause ? await pause : 0;
  if (paused) recordMobileMetric('my_photos_download_event', paused, { my_photos_download_event: 'paused' });
  return paused;
}

/** Account/trip cleanup must never reopen the old SQLite namespace. The
 * session-lock settlement hook awaits the native writer before closing the
 * database; durable `downloading` rows are recovered on same-account login. */
export function abortPhotoDownloadsForContext(context: MyPhotosContext, reason: Error): void {
  photoDownloadExecutions.abortContext(context, reason);
}

export async function resumePhotoDownload(context: MyPhotosContext, id: string): Promise<void> {
  let job = await getPhotoDownload(context, id);
  if (!job || !['paused', 'failed', 'corrupt', 'cancelled'].includes(job.state)) return;
  if (job.state === 'corrupt' && job.stableErrorCode === CORRUPT_FILE_REMOVAL_PENDING) {
    const input = vaultInput(job);
    if (!input) return;
    if (job.encryptedFileUri) {
      await removePhotoVaultFile({ ...input, encryptedUri: job.encryptedFileUri });
    }
    await discardPhotoVaultStaging(input);
    job = await transitionPhotoDownload(context, id, 'corrupt', {
      expectedCurrent: ['corrupt'],
      errorCode: 'LOCAL_FILE_CORRUPT',
    });
  }
  await transitionPhotoDownload(context, id, 'queued', { expectedCurrent: [job.state] });
  recordMobileMetric('my_photos_download_event', 1, { my_photos_download_event: 'resumed' });
}

export async function cancelPhotoDownload(context: MyPhotosContext, id: string): Promise<void> {
  await photoDownloadExecutions.abortAndWait(context, id, new Error('Photo download cancelled.'));
  let job = await getPhotoDownload(context, id);
  if (!job || ['completed', 'removed', 'failed', 'corrupt'].includes(job.state)) return;
  if (job.state !== 'cancelled') {
    await transitionPhotoDownload(context, id, 'cancelled', { expectedCurrent: [job.state] });
    job = await getPhotoDownload(context, id);
  }
  const input = job ? vaultInput(job) : null;
  if (input) await discardPhotoVaultStaging(input);
  recordMobileMetric('my_photos_download_event', 1, { my_photos_download_event: 'cancelled' });
}

export async function removeDownloadedPhoto(context: MyPhotosContext, id: string): Promise<void> {
  let current = await getPhotoDownload(context, id);
  if (!current || current.state === 'removed') return;
  if (['queued', 'waiting_wifi', 'waiting_media_preparation', 'downloading', 'retrying', 'expired_authorization'].includes(current.state)) {
    await cancelPhotoDownload(context, id);
    current = await getPhotoDownload(context, id);
  }
  if (!current || !['completed', 'corrupt', 'failed', 'cancelled', 'paused'].includes(current.state)) return;
  const job = await markPhotoDownloadRemovalRequested(context, id);
  const input = vaultInput(job);
  if (input) {
    if (job.encryptedFileUri) await removePhotoVaultFile({ ...input, encryptedUri: job.encryptedFileUri });
    await discardPhotoVaultStaging(input);
  }
  const latest = await getPhotoDownload(context, id);
  if (latest && ['completed', 'corrupt', 'failed', 'cancelled', 'paused'].includes(latest.state)) {
    await transitionPhotoDownload(context, id, 'removed', { expectedCurrent: [latest.state] });
  }
}

/** Exhaustively removes durable local photo copies without depending on the
 * bounded queue projection used by the UI. Rows remain as tombstones, so the
 * stable `(created_at, id)` cursor cannot skip later records while files are
 * removed. Corrupt rows are included because they may still own ciphertext. */
export async function removeAllCompletedPhotoDownloads(
  context: MyPhotosContext,
  signal: AbortSignal = context.signal,
): Promise<number> {
  let cursor: PhotoDownloadManifestCursor | null = null;
  let removedCount = 0;
  const recentCursors: string[] = [];
  do {
    if (signal.aborted) throw signal.reason instanceof Error
      ? signal.reason
      : new Error('My Photos local removal was cancelled.');
    const page = await listPhotoDownloadManifestPage(context, cursor, 50);
    for (const job of page.items) {
      if (signal.aborted) throw signal.reason instanceof Error
        ? signal.reason
        : new Error('My Photos local removal was cancelled.');
      if (photoStorageActionIncludes(job.state, 'remove_completed_copies')) {
        await removeDownloadedPhoto(context, job.id);
        removedCount += 1;
      }
    }
    cursor = page.nextCursor;
    if (cursor) {
      const encoded = `${cursor.createdAt}|${cursor.id}`;
      if (recentCursors.includes(encoded)) throw new Error('My Photos local manifest cursor repeated.');
      recentCursors.push(encoded);
      if (recentCursors.length > RECENT_DOWNLOAD_ALL_CURSORS) recentCursors.shift();
    }
  } while (cursor);
  return removedCount;
}

/** Explicit destructive storage reset for this account/passenger/trip. It is
 * intentionally separate from Face Scan/search deletion and from the gentler
 * completed-copy removal action. */
export async function clearMyPhotosStorage(
  context: MyPhotosContext,
  signal: AbortSignal = context.signal,
): Promise<number> {
  await photoDownloadExecutions.abortContextAndWait(
    context,
    new Error('My Photos storage is being cleared.'),
  );
  assertMyPhotosContextStillCurrent(context);
  await cancelPhotoDownloadBatches(context);
  await purgePhotoTemporaryFiles();
  let cursor: PhotoDownloadManifestCursor | null = null;
  let removedCount = 0;
  const recentCursors: string[] = [];
  do {
    if (signal.aborted) throw signal.reason instanceof Error
      ? signal.reason : new Error('My Photos storage clearing was cancelled.');
    assertMyPhotosContextStillCurrent(context);
    const page = await listPhotoDownloadManifestPage(context, cursor, 50);
    for (const job of page.items) {
      if (signal.aborted) throw signal.reason instanceof Error
        ? signal.reason : new Error('My Photos storage clearing was cancelled.');
      if (!photoStorageActionIncludes(job.state, 'clear_trip_storage')) continue;
      await removeDownloadedPhoto(context, job.id);
      removedCount += 1;
    }
    cursor = page.nextCursor;
    if (cursor) {
      const encoded = `${cursor.createdAt}|${cursor.id}`;
      if (recentCursors.includes(encoded)) throw new Error('My Photos storage cursor repeated.');
      recentCursors.push(encoded);
      if (recentCursors.length > RECENT_DOWNLOAD_ALL_CURSORS) recentCursors.shift();
    }
  } while (cursor);
  return removedCount;
}

export async function openLocalPhoto(
  context: MyPhotosContext,
  assetId: string,
  quality: DownloadQuality,
  signal?: AbortSignal,
): Promise<LocalPhotoLease | null> {
  const job = await findPhotoDownload(context, assetId, quality);
  if (!job || job.state !== 'completed' || !job.encryptedFileUri) return null;
  const input = vaultInput(job);
  if (!input) return null;
  await assertCanonicalPhotoVaultUri(input, job.encryptedFileUri);
  let file: Awaited<ReturnType<typeof decryptPhotoForViewing>>;
  try {
    file = await decryptPhotoForViewing({ ...input, encryptedUri: job.encryptedFileUri }, signal);
  } catch (error) {
    if (!(error instanceof PhotoVaultIntegrityError)) throw error;
    assertMyPhotosContextStillCurrent(context);
    let errorCode = 'LOCAL_FILE_CORRUPT';
    if (job.encryptedSizeBytes !== null) {
      const status = await inspectPhotoVaultFileMetadata({
        ...input,
        encryptedUri: job.encryptedFileUri,
        expectedEncryptedBytes: job.encryptedSizeBytes,
      });
      if (status === 'missing') errorCode = 'LOCAL_FILE_MISSING';
      else if (status === 'size_mismatch') errorCode = 'LOCAL_FILE_SIZE_MISMATCH';
    }
    await transitionPhotoDownload(context, job.id, 'corrupt', {
      expectedCurrent: ['completed'],
      errorCode: CORRUPT_FILE_REMOVAL_PENDING,
    });
    recordMobileMetric('my_photos_checksum_failure', 1, { outcome: 'failure' });
    try {
      await removePhotoVaultFile({ ...input, encryptedUri: job.encryptedFileUri });
      await discardPhotoVaultStaging(input);
      assertMyPhotosContextStillCurrent(context);
      await transitionPhotoDownload(context, job.id, 'corrupt', {
        expectedCurrent: ['corrupt'],
        errorCode,
      });
    } catch {
      // The durable removal-pending code lets startup reconciliation finish
      // quarantining ciphertext before this job can be retried.
      recordMobileMetric('my_photos_download_event', 1, { my_photos_download_event: 'failed' });
    }
    throw error;
  }
  try {
    assertMyPhotosContextStillCurrent(context);
  } catch (error) {
    releasePhotoView(file);
    throw error;
  }
  let released = false;
  return {
    uri: file.uri,
    mimeType: input.contentType,
    quality: job.quality,
    jobId: job.id,
    release: () => {
      if (released) return;
      released = true;
      releasePhotoView(file);
    },
  };
}

export { photoDownloadStorageSummary };

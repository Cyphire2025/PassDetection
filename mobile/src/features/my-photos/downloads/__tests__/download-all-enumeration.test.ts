import type { MyPhotosAsset, MyPhotosPage, MyPhotosSummary } from '../../api/contracts';
import { ApiError } from '@/core/api/client';
import type { MyPhotosContext } from '../../data/my-photos-context';
import { purgeMyPhotosPrivateTripData } from '../../data/my-photos-repository';
import { getMyPhotosDownloadPlan, getMyPhotosPage } from '../../api/my-photos-api';
import {
  enqueueAndCheckpointDownloadAllPage,
  findPhotoDownload,
  getPhotoDownload,
  listUnfinishedDownloadAllBatches,
  photoDownloadRetainedProgress,
  setDownloadAllBatchState,
  transitionPhotoDownload,
  type PhotoDownloadBatch,
  type PhotoDownloadJob,
} from '../download-repository';
import {
  enumerateDownloadAll,
  isPhotoDownloadDeliveryFailureRetryable,
  openLocalPhoto,
  planFilterPhotoDownloads,
  planAllMatchedPhotoDownloads,
  resumePhotoDownload,
  resumeUnfinishedDownloadAll,
} from '../download-manager';
import { purgeDisabledMyPhotosTrip } from '../photo-feature-disable-cleanup';
import {
  PhotoVaultIntegrityError,
  deletePhotoTripStorage,
  decryptPhotoForViewing,
  discardPhotoVaultStaging,
  inspectPhotoVaultFileMetadata,
  removePhotoVaultFile,
} from '../photo-vault';
import { PhotoDownloadExecutionRegistry } from '../photo-download-execution-registry';

jest.mock('expo-crypto', () => ({ randomUUID: jest.fn(() => 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa') }));
jest.mock('@/core/observability/mobile-observability', () => ({ recordMobileMetric: jest.fn() }));
jest.mock('../../data/my-photos-context', () => ({
  assertMyPhotosContextStillCurrent: jest.fn(),
  myPhotosContextStillCurrent: jest.fn(() => true),
  runWhenMyPhotosContextCurrent: jest.fn((_context, operation) => operation()),
}));
jest.mock('../../api/my-photos-api', () => ({
  authorizeMyPhotosDownloads: jest.fn(),
  getMyPhotosDownloadPlan: jest.fn(),
  getMyPhotosPage: jest.fn(),
  prepareMyPhotosAsset: jest.fn(),
}));
jest.mock('../../data/my-photos-repository', () => ({
  purgeMyPhotosPrivateTripData: jest.fn(),
}));
jest.mock('../download-repository', () => ({
  beginDownloadAllBatch: jest.fn(),
  claimNextPhotoDownload: jest.fn(),
  enqueueAndCheckpointDownloadAllPage: jest.fn(),
  enqueuePhotoDownloads: jest.fn(),
  findPhotoDownload: jest.fn(),
  getPhotoDownload: jest.fn(),
  listPhotoDownloadManifestPage: jest.fn(),
  listUnfinishedDownloadAllBatches: jest.fn(),
  markPhotoDownloadRemovalRequested: jest.fn(),
  nextPhotoDownloadWakeAt: jest.fn(),
  pauseActivePhotoTransfers: jest.fn(),
  photoDownloadRetainedProgress: jest.fn(),
  photoDownloadStorageSummary: jest.fn(),
  recoverPhotoDownloadQueue: jest.fn(),
  registerCompletedPhotoDownload: jest.fn(),
  setDownloadAllBatchState: jest.fn(),
  transitionPhotoDownload: jest.fn(),
  updatePhotoDownloadAuthorizationMetadata: jest.fn(),
  updatePhotoDownloadProgress: jest.fn(),
}));
jest.mock('../photo-vault', () => ({
  PhotoVaultIntegrityError: class PhotoVaultIntegrityError extends Error {},
  PhotoVaultStorageError: class PhotoVaultStorageError extends Error {},
  assertCanonicalPhotoVaultUri: jest.fn(),
  availablePhotoVaultDiskBytes: jest.fn(() => 10_000_000_000),
  deletePhotoTripStorage: jest.fn(),
  decryptPhotoForViewing: jest.fn(),
  discardPhotoVaultStaging: jest.fn(),
  downloadPhotoToVault: jest.fn(),
  inspectPhotoVaultFile: jest.fn(),
  inspectPhotoVaultFileMetadata: jest.fn(),
  photoVaultStorageUsage: jest.fn(async () => ({ accountBytes: 0, appBytes: 0 })),
  purgePhotoTemporaryFiles: jest.fn(),
  releasePhotoView: jest.fn(),
  removePhotoVaultFile: jest.fn(),
}));

const context = {
  namespace: 'tenant.account',
  sessionId: 'session',
  agencyId: 'tenant',
  principalId: 'account',
  role: 'passenger',
  tripId: '11111111-1111-4111-8111-111111111111',
  passengerId: '22222222-2222-4222-8222-222222222222',
  signal: new AbortController().signal,
} satisfies MyPhotosContext;

const batch: PhotoDownloadBatch = {
  id: '33333333-3333-4333-8333-333333333333',
  requestKind: 'all_matched',
  checkpointFilter: 'best',
  selectionFilter: null,
  excludedAssetIds: [],
  cursor: null,
  enqueuedCount: 0,
  enumeratedCount: 0,
  expectedItemCount: 57,
  quality: 'original',
  wifiOnly: true,
  galleryRevision: 9,
  state: 'active',
};

function asset(index: number): MyPhotosAsset {
  return {
    asset_id: `00000000-0000-4000-8000-${index.toString().padStart(12, '0')}`,
    download_qualities: ['original', 'optimized'],
    original_byte_size: 1_000_000 + index,
    original_state: index === 17 ? 'archived_offline' : 'original_available_online',
    availability_state: index === 17 ? 'archived_offline' : 'delivery_available',
    preparing: index === 17,
  } as MyPhotosAsset;
}

function page(filter: 'best' | 'possible', count: number): MyPhotosPage {
  return {
    snapshot_revision: 9,
    filter,
    items: Array.from({ length: count }, (_value, index) => asset(
      filter === 'best' ? index : 100 + index,
    )),
    next_cursor: null,
    page_size: count,
    total_count: count,
  };
}

function completedDownload(): PhotoDownloadJob {
  return {
    id: '66666666-6666-4666-8666-666666666666',
    batchId: null,
    namespace: context.namespace,
    tripId: context.tripId,
    passengerId: context.passengerId,
    assetId: asset(1).asset_id,
    quality: 'original',
    wifiOnly: false,
    state: 'completed',
    deliveryVersion: 1,
    expectedSizeBytes: 1_000_001,
    expectedChecksumSha256: 'a'.repeat(64),
    contentType: 'image/jpeg',
    verifiedPlaintextBytes: 1_000_001,
    encryptedSizeBytes: 1_000_128,
    encryptedFileUri: 'file:///private/photo.enc',
    attemptCount: 1,
    preparationPollCount: 0,
    integrityVerifiedAt: '2026-08-23T10:00:00.000Z',
    nextAttemptAt: null,
    stableErrorCode: null,
    authorizationExpiresAt: null,
    supportsRanges: true,
    createdAt: '2026-08-23T09:59:00.000Z',
    updatedAt: '2026-08-23T10:00:00.000Z',
    completedAt: '2026-08-23T10:00:00.000Z',
  };
}

const mockedGetPage = jest.mocked(getMyPhotosPage);
const mockedGetPlan = jest.mocked(getMyPhotosDownloadPlan);
const mockedCommitPage = jest.mocked(enqueueAndCheckpointDownloadAllPage);
const mockedListBatches = jest.mocked(listUnfinishedDownloadAllBatches);
const mockedSetBatchState = jest.mocked(setDownloadAllBatchState);
const mockedRetainedProgress = jest.mocked(photoDownloadRetainedProgress);
const mockedFindDownload = jest.mocked(findPhotoDownload);
const mockedGetDownload = jest.mocked(getPhotoDownload);
const mockedTransitionDownload = jest.mocked(transitionPhotoDownload);
const mockedDecryptPhoto = jest.mocked(decryptPhotoForViewing);
const mockedDiscardStaging = jest.mocked(discardPhotoVaultStaging);
const mockedInspectMetadata = jest.mocked(inspectPhotoVaultFileMetadata);
const mockedRemoveVaultFile = jest.mocked(removePhotoVaultFile);
const mockedDeleteTripStorage = jest.mocked(deletePhotoTripStorage);
const mockedPurgePrivateTripData = jest.mocked(purgeMyPhotosPrivateTripData);

beforeEach(() => {
  jest.clearAllMocks();
  mockedGetPage.mockImplementation(async (_tripId, filter) => page(filter as 'best' | 'possible', filter === 'best' ? 45 : 12));
  mockedCommitPage.mockImplementation(async (_context, _batch, assetIds) => assetIds.length);
  mockedSetBatchState.mockResolvedValue();
});

it('durably enumerates the 57-match fixture in bounded best/possible pages', async () => {
  await expect(enumerateDownloadAll(context, batch, context.signal)).resolves.toEqual({
    kind: 'all_matched',
    queuedCount: 57,
    batchId: batch.id,
  });

  expect(mockedGetPage).toHaveBeenCalledTimes(2);
  expect(mockedGetPage).toHaveBeenNthCalledWith(1, context.tripId, 'best', {
    cursor: null,
    limit: 48,
    signal: context.signal,
  });
  expect(mockedCommitPage).toHaveBeenNthCalledWith(
    1,
    context,
    batch,
    expect.arrayContaining([expect.any(String)]),
    { filter: 'possible', cursor: null },
  );
  expect(mockedCommitPage.mock.calls[0]?.[2]).toContain(asset(17).asset_id);
  expect(mockedCommitPage).toHaveBeenNthCalledWith(
    2,
    context,
    batch,
    expect.arrayContaining([expect.any(String)]),
    { filter: null, cursor: null },
  );
  expect(mockedSetBatchState).toHaveBeenCalledWith(context, batch.id, 'completed');
});

it('resumes from a durable filter checkpoint and coalesces concurrent restart drains', async () => {
  const resumed = {
    ...batch,
    checkpointFilter: 'possible' as const,
    enqueuedCount: 45,
    enumeratedCount: 45,
  };
  mockedListBatches.mockResolvedValue([resumed]);
  let release!: (value: MyPhotosPage) => void;
  mockedGetPage.mockImplementation(() => new Promise((resolve) => { release = resolve; }));

  const first = resumeUnfinishedDownloadAll(context, context.signal);
  const second = resumeUnfinishedDownloadAll(context, context.signal);
  for (let tick = 0; tick < 10 && mockedGetPage.mock.calls.length === 0; tick += 1) {
    await Promise.resolve();
  }
  expect(mockedGetPage).toHaveBeenCalledTimes(1);
  release(page('possible', 12));
  await expect(Promise.all([first, second])).resolves.toEqual([true, true]);

  expect(mockedGetPage).toHaveBeenCalledTimes(1);
  expect(mockedGetPage).toHaveBeenCalledWith(context.tripId, 'possible', expect.objectContaining({
    cursor: null,
    limit: 48,
  }));
  expect(mockedCommitPage).toHaveBeenCalledTimes(1);
});

it('checkpoints one runtime page before yielding to queued transfers', async () => {
  const firstPage = {
    ...page('best', 48),
    next_cursor: 'next-best-page',
    total_count: 57,
  };
  mockedListBatches.mockResolvedValue([batch]);
  mockedGetPage.mockResolvedValue(firstPage);

  await expect(resumeUnfinishedDownloadAll(context, context.signal)).resolves.toBe(true);

  expect(mockedGetPage).toHaveBeenCalledTimes(1);
  expect(mockedCommitPage).toHaveBeenCalledWith(
    context,
    batch,
    expect.any(Array),
    { filter: 'best', cursor: 'next-best-page' },
  );
  expect(mockedSetBatchState).not.toHaveBeenCalledWith(context, batch.id, 'completed');
});

it('enumerates Select All in one match tier with exclusions and never enters All Group Photos', async () => {
  const filterBatch: PhotoDownloadBatch = {
    ...batch,
    requestKind: 'filter_selection',
    checkpointFilter: 'best',
    selectionFilter: 'best',
    excludedAssetIds: [asset(2).asset_id, asset(7).asset_id],
    expectedItemCount: 43,
  };

  await expect(enumerateDownloadAll(context, filterBatch, context.signal)).resolves.toEqual({
    kind: 'filter_selection',
    queuedCount: 43,
    batchId: filterBatch.id,
  });

  expect(mockedGetPage).toHaveBeenCalledTimes(1);
  expect(mockedGetPage).toHaveBeenCalledWith(context.tripId, 'best', expect.any(Object));
  expect(mockedCommitPage).toHaveBeenCalledWith(
    context,
    filterBatch,
    expect.not.arrayContaining(filterBatch.excludedAssetIds),
    { filter: null, cursor: null },
  );
});

it('builds a bounded-memory Select All plan at the stable filter revision', async () => {
  const summary = {
    gallery: { published_revision: 9 },
    results: { snapshot_revision: 9 },
    search: { best_match_count: 45, possible_match_count: 12 },
  } as MyPhotosSummary;

  const plan = await planFilterPhotoDownloads(
    context,
    summary,
    'best',
    [asset(2).asset_id, asset(7).asset_id],
  );

  expect(plan).toMatchObject({
    kind: 'filter_selection',
    itemCount: 43,
    galleryRevision: 9,
    items: [],
    filterSelection: { filter: 'best' },
  });
  expect(mockedGetPage).toHaveBeenCalledTimes(1);
  expect(plan.filterSelection?.excludedAssetIds).toEqual([
    asset(2).asset_id,
    asset(7).asset_id,
  ]);
});

it('does not credit completed photos from an older match revision in Download All preflight', async () => {
  mockedGetPlan.mockResolvedValue({
    snapshot_revision: 9,
    matched_item_count: 57,
    downloadable_item_count: 57,
    preparing_item_count: 0,
    qualities: [
      {
        quality: 'original',
        supported_item_count: 57,
        exact_byte_total: 57_000_000,
        maximum_item_bytes: 1_000_000,
        estimate_complete: true,
      },
      {
        quality: 'optimized',
        supported_item_count: 57,
        exact_byte_total: 20_000_000,
        maximum_item_bytes: 500_000,
        estimate_complete: true,
      },
    ],
  });
  mockedRetainedProgress.mockResolvedValue({
    completedItemCount: 57,
    verifiedPlaintextBytes: 57_000_000,
  });

  const plan = await planAllMatchedPhotoDownloads(context, {
    gallery: { published_revision: 9 },
    results: { snapshot_revision: 9 },
  } as MyPhotosSummary);

  expect(mockedRetainedProgress).not.toHaveBeenCalled();
  expect(plan.remainingBytesByQuality.original).toBe(57_000_000);
});

it('quarantines same-size post-verification corruption and leaves the exact owned job retryable', async () => {
  const completed = completedDownload();
  const corrupt = {
    ...completed,
    state: 'corrupt' as const,
    stableErrorCode: 'LOCAL_FILE_CORRUPT',
  };
  mockedFindDownload.mockResolvedValue(completed);
  mockedDecryptPhoto.mockRejectedValue(new PhotoVaultIntegrityError('Authenticated chunks changed.'));
  mockedInspectMetadata.mockResolvedValue('present');
  mockedTransitionDownload
    .mockResolvedValueOnce({ ...corrupt, stableErrorCode: 'CORRUPT_FILE_REMOVAL_PENDING' })
    .mockResolvedValueOnce(corrupt)
    .mockResolvedValueOnce({ ...corrupt, state: 'queued', stableErrorCode: null });

  await expect(openLocalPhoto(
    context,
    completed.assetId,
    completed.quality,
    context.signal,
  )).rejects.toBeInstanceOf(PhotoVaultIntegrityError);

  expect(mockedTransitionDownload).toHaveBeenNthCalledWith(
    1,
    context,
    completed.id,
    'corrupt',
    { expectedCurrent: ['completed'], errorCode: 'CORRUPT_FILE_REMOVAL_PENDING' },
  );
  expect(mockedRemoveVaultFile).toHaveBeenCalledWith(expect.objectContaining({
    encryptedUri: completed.encryptedFileUri,
  }));
  expect(mockedDiscardStaging).toHaveBeenCalled();
  expect(mockedTransitionDownload).toHaveBeenNthCalledWith(
    2,
    context,
    completed.id,
    'corrupt',
    { expectedCurrent: ['corrupt'], errorCode: 'LOCAL_FILE_CORRUPT' },
  );

  mockedGetDownload.mockResolvedValue(corrupt);
  await expect(resumePhotoDownload(context, completed.id)).resolves.toBeUndefined();
  expect(mockedTransitionDownload).toHaveBeenNthCalledWith(
    3,
    context,
    completed.id,
    'queued',
    { expectedCurrent: ['corrupt'] },
  );
});

it('classifies the normalized internal delivery timeout as retryable', () => {
  expect(isPhotoDownloadDeliveryFailureRetryable(new ApiError(
    'The photo delivery request timed out.',
    408,
    'PHOTO_DELIVERY_TIMEOUT',
    null,
  ))).toBe(true);
  expect(isPhotoDownloadDeliveryFailureRetryable(new ApiError(
    'The photo delivery contract was invalid.',
    400,
    'INVALID_MEDIA_RESPONSE',
    null,
  ))).toBe(false);
});

it('settles native transfers before purging only the disabled passenger trip', async () => {
  const abortAndWait = jest.spyOn(
    PhotoDownloadExecutionRegistry.prototype,
    'abortContextAndWait',
  ).mockResolvedValue();

  await expect(purgeDisabledMyPhotosTrip(context)).resolves.toBeUndefined();

  expect(abortAndWait).toHaveBeenCalledWith(context, expect.any(Error));
  expect(mockedDeleteTripStorage).toHaveBeenCalledWith(context.namespace, context.tripId);
  expect(mockedPurgePrivateTripData).toHaveBeenCalledWith(context, expect.any(Function));
  expect(mockedDeleteTripStorage.mock.invocationCallOrder[0]).toBeLessThan(
    mockedPurgePrivateTripData.mock.invocationCallOrder[0]!,
  );
  abortAndWait.mockRestore();
});

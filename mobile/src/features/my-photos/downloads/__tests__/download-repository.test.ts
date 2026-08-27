import {
  openAccountDatabase,
  withAccountTransaction,
} from '@/core/storage/database';

import type { MyPhotosContext } from '../../data/my-photos-context';
import {
  enqueueAndCheckpointDownloadAllPage,
  listCompletedPhotoDownloadsPage,
  listPhotoDownloads,
  photoDownloadRetainedProgress,
  recoverPhotoDownloadQueue,
  updatePhotoDownloadProgress,
  type PhotoDownloadBatch,
} from '../download-repository';

jest.mock('expo-crypto', () => ({ randomUUID: jest.fn(() => 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa') }));
jest.mock('@/core/storage/database', () => ({
  openAccountDatabase: jest.fn(),
  withAccountTransaction: jest.fn(async (database, task) => task(database)),
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

const runAsync = jest.fn();
const getFirstAsync = jest.fn();
const getAllAsync = jest.fn();
const database = { runAsync, getFirstAsync, getAllAsync };
const mockedOpen = jest.mocked(openAccountDatabase);
const mockedTransaction = jest.mocked(withAccountTransaction);

beforeEach(() => {
  jest.clearAllMocks();
  mockedOpen.mockResolvedValue(database as never);
  runAsync.mockResolvedValue({ changes: 1 });
});

function completedRow(id: string, completedAt: string) {
  return {
    id,
    batch_id: null,
    account_namespace: context.namespace,
    trip_id: context.tripId,
    passenger_id: context.passengerId,
    media_asset_id: `asset-${id}`,
    quality: 'original',
    wifi_only: 0,
    state: 'completed',
    delivery_version: 1,
    expected_size_bytes: 100,
    expected_checksum_sha256: 'a'.repeat(64),
    content_type: 'image/jpeg',
    verified_plaintext_bytes: 100,
    encrypted_size_bytes: 150,
    encrypted_file_uri: `file:///private/${id}`,
    attempt_count: 1,
    preparation_poll_count: 0,
    integrity_verified_at: completedAt,
    next_attempt_at: null,
    stable_error_code: null,
    authorization_expires_at: null,
    supports_ranges: 1,
    created_at: completedAt,
    updated_at: completedAt,
    completed_at: completedAt,
  };
}

it('recovers interrupted work only inside the account/trip/passenger boundary and reports its count', async () => {
  runAsync
    .mockResolvedValueOnce({ changes: 2 })
    .mockResolvedValue({ changes: 1 });

  await expect(recoverPhotoDownloadQueue(
    context,
    { connected: true, wifi: true },
    '2026-08-23T10:00:00.000Z',
  )).resolves.toBe(2);

  const [sql, ...parameters] = runAsync.mock.calls[0]!;
  expect(sql).toContain("state = 'retrying'");
  expect(sql).toContain("state = 'downloading'");
  expect(parameters).toEqual(expect.arrayContaining([
    context.namespace,
    context.tripId,
    context.passengerId,
  ]));
});

it('persists monotonic verified bytes only for the owned active signed manifest', async () => {
  await expect(updatePhotoDownloadProgress(context, 'job-a', 8 * 1024 * 1024)).resolves.toBeUndefined();
  const [sql, ...parameters] = runAsync.mock.calls[0]!;
  expect(sql).toContain('MAX(verified_plaintext_bytes, ?)');
  expect(sql).toContain("state = 'downloading'");
  expect(sql).toContain('? <= expected_size_bytes');
  expect(parameters).toEqual(expect.arrayContaining([
    'job-a',
    context.namespace,
    context.tripId,
    context.passengerId,
    8 * 1024 * 1024,
  ]));
});

it('commits a Download All page and its resume checkpoint in one transaction', async () => {
  const batch: Pick<PhotoDownloadBatch, 'id' | 'quality' | 'wifiOnly'> = {
    id: '33333333-3333-4333-8333-333333333333',
    quality: 'original',
    wifiOnly: true,
  };
  await expect(enqueueAndCheckpointDownloadAllPage(
    context,
    batch,
    [
      '44444444-4444-4444-8444-444444444444',
      '55555555-5555-4555-8555-555555555555',
    ],
    { filter: 'possible', cursor: 'opaque-cursor' },
  )).resolves.toBe(2);

  expect(mockedTransaction).toHaveBeenCalledTimes(1);
  expect(runAsync).toHaveBeenCalledTimes(3);
  expect(runAsync.mock.calls[0]?.[0]).toContain('INSERT INTO my_photos_downloads');
  expect(runAsync.mock.calls[1]?.[0]).toContain('INSERT INTO my_photos_downloads');
  expect(runAsync.mock.calls[2]?.[0]).toContain('UPDATE my_photos_download_batches');
  expect(runAsync.mock.calls[2]).toEqual(expect.arrayContaining(['possible', 'opaque-cursor', 2]));
});

it('bounds selected retained-progress lookup and sums only the requested quality identities', async () => {
  getFirstAsync.mockResolvedValue({ completed_count: 2, verified_bytes: 16_000_000 });
  await expect(photoDownloadRetainedProgress(context, 'optimized', [
    '44444444-4444-4444-8444-444444444444',
    '55555555-5555-4555-8555-555555555555',
  ])).resolves.toEqual({ completedItemCount: 2, verifiedPlaintextBytes: 16_000_000 });
  const [sql, ...parameters] = getFirstAsync.mock.calls[0]!;
  expect(sql).toContain('media_asset_id IN (?,?)');
  expect(sql).toContain("CASE WHEN state = 'completed' THEN verified_plaintext_bytes ELSE 0 END");
  expect(parameters).toEqual(expect.arrayContaining([
    context.namespace,
    context.tripId,
    context.passengerId,
    'optimized',
  ]));
});

it('pages completed local copies with an owner-scoped descending keyset', async () => {
  getAllAsync.mockResolvedValue([
    completedRow('cccccccc-cccc-4ccc-8ccc-cccccccccccc', '2026-08-23T10:03:00.000Z'),
    completedRow('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', '2026-08-23T10:02:00.000Z'),
    completedRow('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', '2026-08-23T10:01:00.000Z'),
  ]);

  const page = await listCompletedPhotoDownloadsPage(context, null, 2);

  expect(page.items.map((job) => job.id)).toEqual([
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  ]);
  expect(page.previousCursor).toBeNull();
  expect(page.nextCursor).toEqual({
    completedAt: '2026-08-23T10:02:00.000Z',
    id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    direction: 'older',
  });
  const [sql, ...parameters] = getAllAsync.mock.calls[0]!;
  expect(sql).toContain("state = 'completed'");
  expect(sql).toContain('ORDER BY completed_at DESC, id DESC');
  expect(parameters).toEqual([
    context.namespace,
    context.tripId,
    context.passengerId,
    3,
  ]);
});

it('reverses a newer keyset page into stable newest-first display order', async () => {
  getAllAsync.mockResolvedValue([
    completedRow('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', '2026-08-23T10:02:00.000Z'),
    completedRow('cccccccc-cccc-4ccc-8ccc-cccccccccccc', '2026-08-23T10:03:00.000Z'),
  ]);

  const page = await listCompletedPhotoDownloadsPage(context, {
    completedAt: '2026-08-23T10:01:00.000Z',
    id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    direction: 'newer',
  }, 2);

  expect(page.items.map((job) => job.id)).toEqual([
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  ]);
  expect(page.previousCursor).toBeNull();
  expect(page.nextCursor).toEqual({
    completedAt: '2026-08-23T10:02:00.000Z',
    id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    direction: 'older',
  });
  const [sql, ...parameters] = getAllAsync.mock.calls[0]!;
  expect(sql).toContain('completed_at > ?');
  expect(sql).toContain('ORDER BY completed_at ASC, id ASC');
  expect(parameters).toEqual([
    context.namespace,
    context.tripId,
    context.passengerId,
    '2026-08-23T10:01:00.000Z',
    '2026-08-23T10:01:00.000Z',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    3,
  ]);
});

it('loads active work before terminal history so bounded queue views cannot hide transfers', async () => {
  getAllAsync.mockResolvedValue([]);

  await expect(listPhotoDownloads(context, false, 6)).resolves.toEqual([]);

  const [sql, ...parameters] = getAllAsync.mock.calls[0]!;
  expect(sql).toContain("WHEN state IN ('completed', 'cancelled', 'failed', 'corrupt', 'removed') THEN 1");
  expect(sql).toContain('updated_at DESC');
  expect(sql).toContain('id DESC');
  expect(parameters).toEqual([
    context.namespace,
    context.tripId,
    context.passengerId,
    6,
  ]);
});

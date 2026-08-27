import {
  openAccountDatabase,
  withAccountTransaction,
} from '@/core/storage/database';

import { getMyPhotosPage } from '../../api/my-photos-api';
import type { MyPhotosAsset } from '../../api/contracts';
import type { MyPhotosContext } from '../my-photos-context';
import {
  fetchMyPhotosPage,
  loadCachedMyPhotosPage,
} from '../my-photos-repository';

jest.mock('@/core/storage/database', () => ({
  openAccountDatabase: jest.fn(),
  withAccountTransaction: jest.fn(async (database, task) => task(database)),
}));
jest.mock('../../api/my-photos-api', () => ({
  getMyPhotosPage: jest.fn(),
  getMyPhotosSummary: jest.fn(),
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

function asset(index: number): MyPhotosAsset {
  const id = `00000000-0000-4000-8000-${index.toString().padStart(12, '0')}`;
  const descriptor = {
    state: 'preview_available' as const,
    transport: 'development_fixture' as const,
    cache_key: `offline:${index}:thumbnail`,
    max_width: 480,
    max_height: 480,
    resource_path: null,
    authorization_id: null,
    expires_at: null,
  };
  return {
    asset_id: id,
    match_id: `00000000-0000-4000-8001-${index.toString().padStart(12, '0')}`,
    tier: 'best',
    feedback: 'none',
    width: 4_000,
    height: 3_000,
    aspect_ratio: 4 / 3,
    captured_at: '2026-08-23T10:00:00.000Z',
    thumbnail_state: 'preview_available',
    preview_state: 'preview_available',
    thumbnail: descriptor,
    preview: {
      ...descriptor,
      cache_key: `offline:${index}:preview`,
      max_width: 1_600,
      max_height: 1_600,
    },
    original_state: 'original_available_online',
    availability_state: 'delivery_available',
    download_qualities: ['original', 'optimized'],
    original_byte_size: 12_000_000,
    original_checksum_sha256: index.toString(16).padStart(64, '0'),
    preparing: false,
  };
}

const mockedOpen = jest.mocked(openAccountDatabase);
const mockedTransaction = jest.mocked(withAccountTransaction);
const mockedGetPage = jest.mocked(getMyPhotosPage);

beforeEach(() => jest.clearAllMocks());

test('loads the exact cached later page and restores its persisted continuation cursor', async () => {
  const getFirstAsync = jest.fn(async () => ({
    next_cursor: 'opaque-cursor-next-0001',
    cached_at: '2026-08-23T10:05:00.000Z',
  }));
  const getAllAsync = jest.fn(async () => [
    { response_json: JSON.stringify(asset(97)), page_ordinal: 2, item_ordinal: 0 },
  ]);
  mockedOpen.mockResolvedValue({ getFirstAsync, getAllAsync } as never);

  await expect(loadCachedMyPhotosPage(context, 'best', 9, 144, 2)).resolves.toMatchObject({
    source: 'offline',
    cachedAt: '2026-08-23T10:05:00.000Z',
    partial: true,
    value: {
      snapshot_revision: 9,
      filter: 'best',
      next_cursor: 'opaque-cursor-next-0001',
      items: [expect.objectContaining({ asset_id: asset(97).asset_id })],
    },
  });

  expect(getFirstAsync.mock.calls[0]).toEqual(expect.arrayContaining([2]));
  expect(getAllAsync.mock.calls[0]).toEqual(expect.arrayContaining([2]));
});

test('uses the exact later-page cache on a network failure instead of falling back to page zero', async () => {
  const getFirstAsync = jest.fn(async () => ({
    next_cursor: null,
    cached_at: '2026-08-23T10:05:00.000Z',
  }));
  const getAllAsync = jest.fn(async () => [
    { response_json: JSON.stringify(asset(145)), page_ordinal: 3, item_ordinal: 0 },
  ]);
  mockedOpen.mockResolvedValue({ getFirstAsync, getAllAsync } as never);
  mockedGetPage.mockRejectedValue(new TypeError('network unavailable'));

  await expect(fetchMyPhotosPage(
    context,
    'best',
    'opaque-request-cursor-0003',
    3,
    9,
    145,
    jest.fn(),
  )).resolves.toMatchObject({
    source: 'offline',
    value: { items: [expect.objectContaining({ asset_id: asset(145).asset_id })] },
  });
  expect(getFirstAsync.mock.calls[0]).toEqual(expect.arrayContaining([3]));
  expect(getAllAsync.mock.calls[0]).toEqual(expect.arrayContaining([3]));
});

test('deletes only the corrupt page and cursor checkpoint in one transaction', async () => {
  const runAsync = jest.fn(async () => ({ changes: 1 }));
  const database = {
    getFirstAsync: jest.fn(async () => ({
      next_cursor: null,
      cached_at: '2026-08-23T10:05:00.000Z',
    })),
    getAllAsync: jest.fn(async () => [
      { response_json: '{invalid-json', page_ordinal: 4, item_ordinal: 0 },
    ]),
    runAsync,
  };
  mockedOpen.mockResolvedValue(database as never);

  await expect(loadCachedMyPhotosPage(context, 'possible', 9, 200, 4)).resolves.toBeNull();

  expect(mockedTransaction).toHaveBeenCalledTimes(1);
  expect(runAsync).toHaveBeenCalledTimes(2);
  for (const call of runAsync.mock.calls) {
    expect(call).toEqual(expect.arrayContaining([
      context.namespace,
      context.tripId,
      context.passengerId,
      9,
      'possible',
      4,
    ]));
  }
});

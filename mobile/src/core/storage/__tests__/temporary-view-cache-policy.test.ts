import {
  TEMPORARY_VIEW_CACHE_MAX_BYTES,
  temporaryViewCacheEvictions,
} from '../temporary-view-cache-policy';

test('evicts least-recent previews while retaining the active verified document', () => {
  expect(temporaryViewCacheEvictions([
    { key: 'oldest', sizeBytes: 10, lastAccessedAt: 1 },
    { key: 'middle', sizeBytes: 10, lastAccessedAt: 2 },
    { key: 'recent', sizeBytes: 10, lastAccessedAt: 3 },
    { key: 'active', sizeBytes: 10, lastAccessedAt: 4 },
  ], 'active')).toEqual(['oldest']);
});

test('enforces the byte ceiling without evicting the only active preview', () => {
  expect(temporaryViewCacheEvictions([
    { key: 'old', sizeBytes: TEMPORARY_VIEW_CACHE_MAX_BYTES, lastAccessedAt: 1 },
    { key: 'active', sizeBytes: 1024, lastAccessedAt: 2 },
  ], 'active')).toEqual(['old']);
  expect(temporaryViewCacheEvictions([
    { key: 'active', sizeBytes: TEMPORARY_VIEW_CACHE_MAX_BYTES + 1, lastAccessedAt: 1 },
  ], 'active')).toEqual([]);
});

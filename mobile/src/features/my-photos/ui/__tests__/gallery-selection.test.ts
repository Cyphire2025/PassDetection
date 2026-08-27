import {
  canSelectEveryFilterResult,
  emptyGallerySelection,
  galleryAssetSelected,
  gallerySelectionCount,
  selectEveryFilterResult,
  toggleGalleryAsset,
} from '../gallery-selection';

test('explicit selection is immutable and coalesces toggles', () => {
  const first = toggleGalleryAsset(emptyGallerySelection, 'asset-1');
  const second = toggleGalleryAsset(first, 'asset-1');
  expect(gallerySelectionCount(first)).toBe(1);
  expect(gallerySelectionCount(second)).toBe(0);
  expect(gallerySelectionCount(emptyGallerySelection)).toBe(0);
});

test('select-all remains scoped to the active filter and tracks exclusions without loading all rows', () => {
  const allBest = selectEveryFilterResult(43);
  expect(allBest.mode).toBe('all_filter');
  expect(gallerySelectionCount(allBest)).toBe(43);
  const excluded = toggleGalleryAsset(allBest, 'asset-7');
  expect(galleryAssetSelected(excluded, 'asset-7')).toBe(false);
  expect(gallerySelectionCount(excluded)).toBe(42);
  expect('assetIds' in excluded).toBe(false);
});

test('bulk selection is intentionally unavailable for All Group Photos', () => {
  expect(canSelectEveryFilterResult('best')).toBe(true);
  expect(canSelectEveryFilterResult('possible')).toBe(true);
  expect(canSelectEveryFilterResult('all')).toBe(false);
});

import {
  clearGalleryScrollAnchors,
  readGalleryScrollAnchor,
  rememberGalleryScrollAnchor,
} from '../gallery-scroll-anchor';

beforeEach(clearGalleryScrollAnchors);

test('scopes a bounded gallery anchor by account, trip, revision, and filter', () => {
  const boundary = 'account-a:trip-a:revision-3:best';
  rememberGalleryScrollAnchor(boundary, { assetId: 'asset-57', absoluteIndex: 56 });

  expect(readGalleryScrollAnchor(boundary)).toEqual({ assetId: 'asset-57', absoluteIndex: 56 });
  expect(readGalleryScrollAnchor('account-b:trip-a:revision-3:best')).toBeNull();
  expect(readGalleryScrollAnchor('account-a:trip-b:revision-3:best')).toBeNull();
});

test('evicts old anchors instead of retaining unbounded account navigation history', () => {
  for (let index = 0; index < 40; index += 1) {
    rememberGalleryScrollAnchor(`boundary-${index}`, { assetId: `asset-${index}`, absoluteIndex: index });
  }
  expect(readGalleryScrollAnchor('boundary-0')).toBeNull();
  expect(readGalleryScrollAnchor('boundary-39')).toEqual({ assetId: 'asset-39', absoluteIndex: 39 });
});

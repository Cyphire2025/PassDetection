import assert from 'node:assert/strict';
import test from 'node:test';

import {
  assertSyntheticIdentityBoundary,
  createMyPhotosScaleFixture,
  MY_PHOTOS_SCALE_BUDGET,
  pageMyPhotosMatches,
} from './my-photos-load-contract.mjs';

test('creates the reproducible 5,000-asset and 57-match development scenario', () => {
  const first = createMyPhotosScaleFixture();
  const second = createMyPhotosScaleFixture();
  const passengerA = first.passengerMatches[first.identities.passengerAId];

  assert.equal(first.assets.length, 5_000);
  assert.equal(passengerA.length, 57);
  assert.equal(passengerA.filter((match) => match.tier === 'best').length, 38);
  assert.equal(passengerA.filter((match) => match.tier === 'possible').length, 19);
  assert.equal(new Set(first.assets.map((asset) => asset.id)).size, 5_000);
  assert.equal(first.assets[0].id, second.assets[0].id);
  assert.equal(
    first.assets[first.assets.length - 1].id,
    second.assets[second.assets.length - 1].id,
  );
  assert.equal(assertSyntheticIdentityBoundary(first), true);
});

test('keeps one shared media asset while associating it with two passengers', () => {
  const fixture = createMyPhotosScaleFixture();
  const passengerA = fixture.passengerMatches[fixture.identities.passengerAId];
  const passengerB = fixture.passengerMatches[fixture.identities.passengerBId];

  assert.equal(passengerA.some((match) => match.assetId === fixture.sharedAssetId), true);
  assert.equal(passengerB.some((match) => match.assetId === fixture.sharedAssetId), true);
  assert.equal(fixture.assets.filter((asset) => asset.id === fixture.sharedAssetId).length, 1);
  assert.ok(fixture.assets[0].faceOccurrenceIds.length > 1);
});

test('models portrait, landscape, online, offline, preparation, resume, and corruption states', () => {
  const fixture = createMyPhotosScaleFixture();

  assert.equal(fixture.assets.some((asset) => asset.aspectRatio > 1), true);
  assert.equal(fixture.assets.some((asset) => asset.aspectRatio < 1), true);
  assert.equal(
    fixture.assets.some((asset) => asset.originalAvailability === 'archived_offline'),
    true,
  );
  assert.equal(
    fixture.assets.some((asset) => asset.originalAvailability === 'preparing_delivery'),
    true,
  );
  assert.equal(fixture.interruptedDownload.state, 'paused');
  assert.equal(fixture.interruptedDownload.rangeResumeSupported, true);
  assert.ok(fixture.assets.some((asset) => asset.id === fixture.corruptDownloadAssetId));
  assert.notEqual(fixture.galleryRevision, fixture.previousGalleryRevision);
});

test('pages matches by stable revision without an eager all-assets response', () => {
  const fixture = createMyPhotosScaleFixture();
  const matches = fixture.passengerMatches[fixture.identities.passengerAId];
  const first = pageMyPhotosMatches({ matches, revision: fixture.galleryRevision });
  const second = pageMyPhotosMatches({
    matches,
    revision: fixture.galleryRevision,
    cursor: first.nextCursor,
  });

  assert.equal(first.items.length, MY_PHOTOS_SCALE_BUDGET.clientPageSize);
  assert.equal(second.items.length, 9);
  assert.equal(second.nextCursor, null);
  assert.equal(new Set([...first.items, ...second.items].map((item) => item.assetId)).size, 57);
  assert.ok(first.items.length < fixture.assets.length);
});

test('fails closed on excessive page sizes, stale revisions, and malformed fixtures', () => {
  const fixture = createMyPhotosScaleFixture();
  const matches = fixture.passengerMatches[fixture.identities.passengerAId];
  const first = pageMyPhotosMatches({ matches, revision: fixture.galleryRevision });

  assert.throws(
    () => pageMyPhotosMatches({
      matches,
      revision: fixture.galleryRevision,
      limit: MY_PHOTOS_SCALE_BUDGET.serverHardPageMaximum + 1,
    }),
    /hard maximum/,
  );
  assert.throws(
    () => pageMyPhotosMatches({
      matches,
      revision: fixture.previousGalleryRevision,
      cursor: first.nextCursor,
    }),
    /requested revision/,
  );
  assert.throws(() => createMyPhotosScaleFixture({ assetCount: 10, matchCount: 11 }), /exceed/);
});

test('publishes an explicit conservative download concurrency budget', () => {
  assert.equal(MY_PHOTOS_SCALE_BUDGET.downloadConcurrency, 2);
  assert.equal(MY_PHOTOS_SCALE_BUDGET.serverHardPageMaximum, 60);
});

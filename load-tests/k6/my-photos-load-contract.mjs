const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export const MY_PHOTOS_SCALE_BUDGET = Object.freeze({
  assetCount: 5_000,
  representativeMatchCount: 57,
  bestMatchCount: 38,
  possibleMatchCount: 19,
  clientPageSize: 48,
  serverHardPageMaximum: 60,
  downloadConcurrency: 2,
});

const SYNTHETIC_IDENTITIES = Object.freeze({
  tenantId: '10000000-0000-4000-8000-000000000001',
  tripId: '20000000-0000-4000-8000-000000000001',
  passengerAId: '30000000-0000-4000-8000-000000000001',
  passengerBId: '30000000-0000-4000-8000-000000000002',
});

function positiveInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new Error(`${name} must be a positive safe integer`);
  }
  return value;
}

function assetId(index) {
  const suffix = String(index + 1).padStart(12, '0');
  return `40000000-0000-4000-8000-${suffix}`;
}

function faceOccurrenceId(index, occurrence) {
  const suffix = String((index * 10) + occurrence + 1).padStart(12, '0');
  return `50000000-0000-4000-8000-${suffix}`;
}

function availabilityFor(index) {
  if (index === 11) return 'preparing_delivery';
  if (index % 29 === 0) return 'archived_offline';
  return 'original_available_online';
}

function dimensionsFor(index) {
  if (index % 2 === 0) return Object.freeze({ width: 1_600, height: 1_200 });
  return Object.freeze({ width: 1_200, height: 1_600 });
}

function createAsset(index) {
  const dimensions = dimensionsFor(index);
  const id = assetId(index);
  const faceCount = index === 0 ? 4 : 1 + (index % 3);
  return Object.freeze({
    id,
    tenantId: SYNTHETIC_IDENTITIES.tenantId,
    tripId: SYNTHETIC_IDENTITIES.tripId,
    sortKey: `2030-01-${String(31 - (index % 28)).padStart(2, '0')}T12:00:00.000Z:${id}`,
    width: dimensions.width,
    height: dimensions.height,
    aspectRatio: dimensions.width / dimensions.height,
    previewAvailability: 'preview_available',
    originalAvailability: availabilityFor(index),
    originalByteSize: 8_000_000 + (index * 997),
    checksumSha256: String(index + 1).padStart(64, '0'),
    faceOccurrenceIds: Object.freeze(
      Array.from({ length: faceCount }, (_, occurrence) => faceOccurrenceId(index, occurrence)),
    ),
  });
}

function createMatch(asset, index) {
  return Object.freeze({
    assetId: asset.id,
    sortKey: asset.sortKey,
    tier: index < MY_PHOTOS_SCALE_BUDGET.bestMatchCount ? 'best' : 'possible',
    previewAvailability: asset.previewAvailability,
    originalAvailability: asset.originalAvailability,
  });
}

export function createMyPhotosScaleFixture(overrides = {}) {
  const assetCount = positiveInteger(
    overrides.assetCount ?? MY_PHOTOS_SCALE_BUDGET.assetCount,
    'assetCount',
  );
  const matchCount = positiveInteger(
    overrides.matchCount ?? MY_PHOTOS_SCALE_BUDGET.representativeMatchCount,
    'matchCount',
  );
  if (matchCount > assetCount) throw new Error('matchCount cannot exceed assetCount');

  const assets = Object.freeze(Array.from({ length: assetCount }, (_, index) => createAsset(index)));
  const matches = Object.freeze(
    assets.slice(0, matchCount).map((asset, index) => createMatch(asset, index)),
  );
  const sharedAsset = assets[0];
  if (!sharedAsset) throw new Error('The synthetic fixture requires at least one asset');

  return Object.freeze({
    schemaVersion: 1,
    galleryRevision: 'synthetic-gallery-revision-2',
    previousGalleryRevision: 'synthetic-gallery-revision-1',
    newPhotoCount: 7,
    identities: SYNTHETIC_IDENTITIES,
    assets,
    passengerMatches: Object.freeze({
      [SYNTHETIC_IDENTITIES.passengerAId]: matches,
      [SYNTHETIC_IDENTITIES.passengerBId]: Object.freeze([
        Object.freeze({ ...createMatch(sharedAsset, 0), tier: 'best' }),
      ]),
    }),
    sharedAssetId: sharedAsset.id,
    corruptDownloadAssetId: assets[7]?.id ?? sharedAsset.id,
    interruptedDownload: Object.freeze({
      assetId: assets[3]?.id ?? sharedAsset.id,
      state: 'paused',
      verifiedBytes: 2_097_152,
      rangeResumeSupported: true,
    }),
  });
}

function cursorFor(revision, match) {
  return `${revision}|${match.sortKey}`;
}

export function pageMyPhotosMatches({
  matches,
  revision,
  cursor = null,
  limit = MY_PHOTOS_SCALE_BUDGET.clientPageSize,
}) {
  if (!Array.isArray(matches)) throw new Error('matches must be an array');
  if (typeof revision !== 'string' || revision.length < 1 || revision.includes('|')) {
    throw new Error('revision is invalid');
  }
  positiveInteger(limit, 'limit');
  if (limit > MY_PHOTOS_SCALE_BUDGET.serverHardPageMaximum) {
    throw new Error(
      `limit exceeds the hard maximum of ${MY_PHOTOS_SCALE_BUDGET.serverHardPageMaximum}`,
    );
  }

  let start = 0;
  if (cursor !== null) {
    if (typeof cursor !== 'string' || !cursor.startsWith(`${revision}|`)) {
      throw new Error('cursor does not belong to the requested revision');
    }
    const previousIndex = matches.findIndex((match) => cursorFor(revision, match) === cursor);
    if (previousIndex < 0) throw new Error('cursor is invalid or no longer in the snapshot');
    start = previousIndex + 1;
  }

  const items = Object.freeze(matches.slice(start, start + limit));
  const last = items.length > 0 ? items[items.length - 1] : undefined;
  const nextCursor = last && start + items.length < matches.length
    ? cursorFor(revision, last)
    : null;
  return Object.freeze({
    revision,
    items,
    nextCursor,
  });
}

export function assertSyntheticIdentityBoundary(fixture) {
  const { identities } = fixture;
  for (const [name, value] of Object.entries(identities)) {
    if (!UUID_PATTERN.test(value)) throw new Error(`${name} is not a synthetic UUID`);
  }
  for (const asset of fixture.assets) {
    if (asset.tenantId !== identities.tenantId || asset.tripId !== identities.tripId) {
      throw new Error('Synthetic asset escaped its tenant/trip boundary');
    }
  }
  return true;
}

import {
  MyPhotosPageSchema,
  type MyPhotosPage,
  type MyPhotosSummary,
} from '../../api/contracts';
import {
  assertMyPhotosPageContext,
  assertMyPhotosSummaryContext,
  isMyPhotosCachedMetadataPartial,
} from '../my-photos-repository';
import { myPhotosSnapshotRevisionForFilter } from '../gallery-window';

const tripId = '11111111-1111-4111-8111-111111111111';

it('rejects a validly shaped summary returned for a stale selected trip', () => {
  expect(() => assertMyPhotosSummaryContext(
    { tripId },
    { group_id: '22222222-2222-4222-8222-222222222222' } as MyPhotosSummary,
  )).toThrow('another trip');
});

it('rejects first-page filter and revision mismatches before cache publication', () => {
  const page = {
    filter: 'best',
    snapshot_revision: 8,
  } as MyPhotosPage;
  expect(() => assertMyPhotosPageContext(page, 'possible', 8)).toThrow('FILTER_CHANGED');
  expect(() => assertMyPhotosPageContext(page, 'best', 9)).toThrow('REVISION_CHANGED');
  expect(() => assertMyPhotosPageContext(page, 'best', 8)).not.toThrow();
});

it('validates refresh fallback matches against their active result snapshot, not vNext gallery', () => {
  const refreshing = {
    experience_state: 'searching',
    gallery: { published_revision: 10 },
    results: { snapshot_revision: 9, match_count: 57 },
  } as MyPhotosSummary;
  const bestRevision = myPhotosSnapshotRevisionForFilter(refreshing, 'best');
  const allRevision = myPhotosSnapshotRevisionForFilter(refreshing, 'all');

  expect(bestRevision).toBe(9);
  expect(allRevision).toBe(10);
  expect(() => assertMyPhotosPageContext({
    filter: 'best', snapshot_revision: 9,
  } as MyPhotosPage, 'best', bestRevision)).not.toThrow();
  expect(() => assertMyPhotosPageContext({
    filter: 'best', snapshot_revision: 10,
  } as MyPhotosPage, 'best', bestRevision)).toThrow('REVISION_CHANGED');
});

it('surfaces a cached 48-of-57 result window as partial offline metadata', () => {
  const cached = {
    results: { match_count: 57 },
    gallery: { all_group_photos_enabled: false, total_asset_count: 5_000 },
  } as MyPhotosSummary;
  expect(isMyPhotosCachedMetadataPartial(cached, 48)).toBe(true);
  expect(isMyPhotosCachedMetadataPartial(cached, 57)).toBe(false);
});

it('requires even an empty ready page to identify its positive stable snapshot', () => {
  const emptyPage = {
    snapshot_revision: 1,
    filter: 'best',
    items: [],
    next_cursor: null,
    page_size: 40,
    total_count: 0,
  };
  expect(() => MyPhotosPageSchema.parse(emptyPage)).not.toThrow();
  expect(() => MyPhotosPageSchema.parse({ ...emptyPage, snapshot_revision: 0 })).toThrow();
});

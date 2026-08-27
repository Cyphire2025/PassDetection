import type { MyPhotosSummary } from '../../api/contracts';
import {
  initialMyPhotosGalleryFilter,
  shouldShowMyPhotosGallery,
} from '../gallery-visibility';

function summary(
  experienceState: MyPhotosSummary['experience_state'],
  allGroupPhotosEnabled: boolean,
  matchCount = 0,
): MyPhotosSummary {
  return {
    experience_state: experienceState,
    gallery: { all_group_photos_enabled: allGroupPhotosEnabled },
    results: { match_count: matchCount },
  } as MyPhotosSummary;
}

test('makes the organizer-controlled All Group Photos fallback reachable after no matches', () => {
  const fallback = summary('no_matches', true);
  expect(shouldShowMyPhotosGallery(fallback)).toBe(true);
  expect(initialMyPhotosGalleryFilter(fallback)).toBe('all');
});

test('does not bypass organizer policy when the fallback is disabled', () => {
  const unavailable = summary('no_matches', false);
  expect(shouldShowMyPhotosGallery(unavailable)).toBe(false);
  expect(initialMyPhotosGalleryFilter(unavailable)).toBe('best');
});

test('keeps the atomically published prior match grid visible during a revision refresh', () => {
  expect(shouldShowMyPhotosGallery(summary('search_queued', false, 57))).toBe(true);
  expect(shouldShowMyPhotosGallery(summary('searching', false, 57))).toBe(true);
  expect(shouldShowMyPhotosGallery(summary('searching', false, 0))).toBe(false);
});

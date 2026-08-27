import type { MatchFilter, MyPhotosSummary } from '../api/contracts';

const RESULT_STATES: ReadonlySet<MyPhotosSummary['experience_state']> = new Set([
  'matches_preparing',
  'matches_ready',
  'offline_results',
  'partial_offline_results',
]);

export function shouldShowMyPhotosGallery(summary: MyPhotosSummary): boolean {
  return RESULT_STATES.has(summary.experience_state)
    || (
      (summary.experience_state === 'search_queued' || summary.experience_state === 'searching')
      && summary.results.match_count > 0
    )
    || (summary.experience_state === 'enrollment_deleted' && summary.results.match_count > 0)
    || (summary.experience_state === 'no_matches' && summary.gallery.all_group_photos_enabled);
}

export function initialMyPhotosGalleryFilter(summary: MyPhotosSummary): MatchFilter {
  return summary.results.match_count === 0 && summary.gallery.all_group_photos_enabled
    ? 'all'
    : 'best';
}

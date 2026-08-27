import type {
  MatchFilter,
  MyPhotosAsset,
  MyPhotosPage,
  MyPhotosSummary,
} from '../api/contracts';

export const MY_PHOTOS_PAGE_SIZE = 48;
export const MY_PHOTOS_MAX_PAGE_SIZE = 60;
export const MY_PHOTOS_MAX_RESIDENT_PAGES = 4;
export const MY_PHOTOS_MAX_RESIDENT_ITEMS = MY_PHOTOS_MAX_PAGE_SIZE * MY_PHOTOS_MAX_RESIDENT_PAGES;
export const MY_PHOTOS_RECENT_CURSOR_LIMIT = 8;

export class GalleryPaginationError extends Error {
  readonly code:
    | 'DUPLICATE_ASSET'
    | 'REPEATED_CURSOR'
    | 'REVISION_CHANGED'
    | 'FILTER_CHANGED'
    | 'TRACKING_LIMIT_EXCEEDED';

  constructor(code: GalleryPaginationError['code']) {
    super(`My Photos pagination failed: ${code}.`);
    this.name = 'GalleryPaginationError';
    this.code = code;
  }
}

export type GalleryWindow = Readonly<{
  pages: readonly MyPhotosPage[];
  items: readonly MyPhotosAsset[];
  recentRequestCursors: readonly string[];
}>;

export const emptyGalleryWindow: GalleryWindow = Object.freeze({
  pages: Object.freeze([]),
  items: Object.freeze([]),
  recentRequestCursors: Object.freeze([]),
});

export type GalleryPageDirection = 'forward' | 'backward' | 'revisit';

/** Adds one authoritative cursor page while keeping Hermes memory bounded. */
export function appendGalleryPage(
  current: GalleryWindow,
  page: MyPhotosPage,
  requestCursor: string | null,
  direction: GalleryPageDirection = 'forward',
): GalleryWindow {
  const previous = direction === 'backward' ? current.pages[0] : current.pages.at(-1);
  if (previous && previous.snapshot_revision !== page.snapshot_revision) {
    throw new GalleryPaginationError('REVISION_CHANGED');
  }
  if (previous && previous.filter !== page.filter) {
    throw new GalleryPaginationError('FILTER_CHANGED');
  }
  if (
    direction === 'forward'
    && requestCursor
    && current.recentRequestCursors.includes(requestCursor)
  ) {
    throw new GalleryPaginationError('REPEATED_CURSOR');
  }
  if (
    page.next_cursor
    && (
      page.next_cursor === requestCursor
      || (direction === 'forward' && current.recentRequestCursors.includes(page.next_cursor))
    )
  ) {
    throw new GalleryPaginationError('REPEATED_CURSOR');
  }

  const incomingIds = page.items.map((item) => item.asset_id);
  const residentIds = new Set(current.items.map((item) => item.asset_id));
  if (incomingIds.some((assetId) => residentIds.has(assetId))) {
    throw new GalleryPaginationError('DUPLICATE_ASSET');
  }

  const retainedPages = direction === 'backward'
    ? [page, ...current.pages].slice(0, MY_PHOTOS_MAX_RESIDENT_PAGES)
    : [...current.pages, page].slice(-MY_PHOTOS_MAX_RESIDENT_PAGES);
  const items = retainedPages.flatMap((entry) => entry.items);
  if (new Set(items.map((item) => item.asset_id)).size !== items.length) {
    throw new GalleryPaginationError('DUPLICATE_ASSET');
  }
  const recentRequestCursors = requestCursor
    ? [...current.recentRequestCursors.filter((value) => value !== requestCursor), requestCursor]
      .slice(-MY_PHOTOS_RECENT_CURSOR_LIMIT)
    : current.recentRequestCursors;
  return Object.freeze({
    pages: Object.freeze(retainedPages),
    items: Object.freeze(items),
    recentRequestCursors: Object.freeze(recentRequestCursors),
  });
}

/** Mutable behavior is encapsulated behind a query-key-scoped instance so
 * React render never reads or writes a ref while network callbacks can still
 * validate the resident window. */
export class GalleryWindowTracker {
  private current: GalleryWindow = emptyGalleryWindow;

  constructor(
    pages: readonly MyPhotosPage[] = [],
    requestCursors: readonly (string | null)[] = [],
  ) {
    if (pages.length !== requestCursors.length) {
      throw new Error('Gallery tracker seed is incomplete.');
    }
    for (let index = 0; index < pages.length; index += 1) {
      const page = pages[index];
      if (!page) continue;
      this.current = appendGalleryPage(
        this.current,
        page,
        requestCursors[index] ?? null,
        'revisit',
      );
    }
  }

  reset(): void {
    this.current = emptyGalleryWindow;
  }

  snapshot(): GalleryWindow {
    return this.current;
  }

  preview(page: MyPhotosPage, cursor: string | null, direction: GalleryPageDirection): void {
    appendGalleryPage(this.current, page, cursor, direction);
  }

  commit(page: MyPhotosPage, cursor: string | null, direction: GalleryPageDirection): void {
    this.current = appendGalleryPage(this.current, page, cursor, direction);
  }
}

export function myPhotosTotalForFilter(
  summary: MyPhotosSummary | null,
  filter: MatchFilter,
): number {
  if (!summary) return 0;
  return filter === 'best'
    ? summary.search?.best_match_count ?? 0
    : filter === 'possible'
      ? summary.search?.possible_match_count ?? 0
      : summary.gallery.total_asset_count;
}

/** Best/Possible remain on the atomically published passenger-match snapshot
 * while a newer group revision is searched. All Group Photos follows the
 * current gallery publication independently. */
export function myPhotosSnapshotRevisionForFilter(
  summary: MyPhotosSummary,
  filter: MatchFilter,
): number {
  return filter === 'all'
    ? summary.gallery.published_revision
    : summary.results.snapshot_revision;
}

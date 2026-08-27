import type { MyPhotosAsset, MyPhotosPage } from '../../api/contracts';
import {
  appendGalleryPage,
  emptyGalleryWindow,
  GalleryWindowTracker,
  myPhotosTotalForFilter,
  MY_PHOTOS_MAX_RESIDENT_ITEMS,
  MY_PHOTOS_PAGE_SIZE,
  MY_PHOTOS_RECENT_CURSOR_LIMIT,
} from '../gallery-window';

function uuid(index: number): string {
  return `00000000-0000-4000-8000-${index.toString().padStart(12, '0')}`;
}

function asset(index: number): MyPhotosAsset {
  const variant = {
    state: 'preview_available' as const,
    transport: 'development_fixture' as const,
    cache_key: `synthetic:${index}:v2`,
    max_width: 480,
    max_height: 480,
    resource_path: null,
    authorization_id: null,
    expires_at: null,
  };
  return {
    asset_id: uuid(index),
    match_id: uuid(index + 6_000),
    tier: index % 5 === 0 ? 'possible' : 'best',
    feedback: 'none',
    width: index % 2 ? 4_000 : 3_000,
    height: index % 2 ? 3_000 : 4_000,
    aspect_ratio: index % 2 ? 4 / 3 : 3 / 4,
    captured_at: '2026-08-23T10:00:00Z',
    thumbnail_state: 'preview_available',
    preview_state: 'preview_available',
    thumbnail: variant,
    preview: { ...variant, cache_key: `synthetic:${index}:preview:v2`, max_width: 1_600, max_height: 1_600 },
    original_state: index % 17 === 0 ? 'archived_offline' : 'original_available_online',
    availability_state: index % 17 === 0 ? 'archived_offline' : 'preview_available',
    download_qualities: ['original', 'optimized'],
    original_byte_size: 12_000_000,
    original_checksum_sha256: index.toString(16).padStart(64, '0'),
    preparing: index % 17 === 0,
  };
}

function page(start: number, count = MY_PHOTOS_PAGE_SIZE): MyPhotosPage {
  return {
    snapshot_revision: 2,
    filter: 'all',
    items: Array.from({ length: count }, (_, offset) => asset(start + offset)),
    next_cursor: start + count < 5_000 ? `cursor-${start + count}` : null,
    page_size: count,
    total_count: 5_000,
  };
}

describe('bounded My Photos gallery paging', () => {
  it('models 5,000 assets without retaining the complete gallery', () => {
    let window = emptyGalleryWindow;
    let cursor: string | null = null;
    for (let start = 0; start < 5_000; start += MY_PHOTOS_PAGE_SIZE) {
      const count = Math.min(MY_PHOTOS_PAGE_SIZE, 5_000 - start);
      const next = page(start, count);
      window = appendGalleryPage(window, next, cursor);
      cursor = next.next_cursor;
      expect(window.items.length).toBeLessThanOrEqual(MY_PHOTOS_MAX_RESIDENT_ITEMS);
    }
    expect(window.items).toHaveLength(5_000 % MY_PHOTOS_PAGE_SIZE + 3 * MY_PHOTOS_PAGE_SIZE);
  });

  it('represents the 57-match demo using best and possible tiers', () => {
    const matches = Array.from({ length: 57 }, (_, index) => asset(index));
    expect(matches.filter((item) => item.tier === 'best')).toHaveLength(45);
    expect(matches.filter((item) => item.tier === 'possible')).toHaveLength(12);
  });

  it('rejects a repeated cursor and duplicated asset', () => {
    const first = appendGalleryPage(emptyGalleryWindow, page(0), null);
    const second = appendGalleryPage(first, page(48), 'cursor-48');
    expect(() => appendGalleryPage(second, page(96), 'cursor-48')).toThrow('REPEATED_CURSOR');
    const duplicate = page(48);
    duplicate.items[0] = asset(1);
    expect(() => appendGalleryPage(first, { ...duplicate, next_cursor: 'cursor-96' }, 'fresh')).toThrow('DUPLICATE_ASSET');
  });

  it('keeps JavaScript tracking bounded while traversing the complete scale fixture', () => {
    let window = emptyGalleryWindow;
    let cursor: string | null = null;
    for (let start = 0; start < 48 * 40; start += 48) {
      const next = page(start);
      window = appendGalleryPage(window, next, cursor);
      cursor = next.next_cursor;
    }
    expect(window.pages).toHaveLength(4);
    expect(window.items.length).toBeLessThanOrEqual(MY_PHOTOS_MAX_RESIDENT_ITEMS);
    expect(window.recentRequestCursors.length).toBeLessThanOrEqual(MY_PHOTOS_RECENT_CURSOR_LIMIT);
  });

  it('supports backward navigation after forward page eviction without retaining 5,000 records', () => {
    let window = emptyGalleryWindow;
    let cursor: string | null = null;
    for (let start = 0; start < MY_PHOTOS_PAGE_SIZE * 6; start += MY_PHOTOS_PAGE_SIZE) {
      const next = page(start);
      window = appendGalleryPage(window, next, cursor);
      cursor = next.next_cursor;
    }
    expect(window.pages[0]?.items[0]?.asset_id).toBe(asset(MY_PHOTOS_PAGE_SIZE * 2).asset_id);

    window = appendGalleryPage(
      window,
      page(MY_PHOTOS_PAGE_SIZE),
      `cursor-${MY_PHOTOS_PAGE_SIZE}`,
      'backward',
    );
    expect(window.pages[0]?.items[0]?.asset_id).toBe(asset(MY_PHOTOS_PAGE_SIZE).asset_id);
    expect(window.pages).toHaveLength(4);
    expect(window.items.length).toBeLessThanOrEqual(MY_PHOTOS_MAX_RESIDENT_ITEMS);
  });

  it('seeds an independent viewer window without mutating the grid scroll window', () => {
    const seededPages = [page(96), page(144), page(192), page(240)];
    const cursors = ['cursor-96', 'cursor-144', 'cursor-192', 'cursor-240'];
    const grid = new GalleryWindowTracker(seededPages, cursors);
    const viewer = new GalleryWindowTracker(seededPages, cursors);
    const gridBefore = grid.snapshot();

    viewer.commit(page(288), 'cursor-288', 'forward');

    expect(grid.snapshot()).toBe(gridBefore);
    expect(grid.snapshot().pages[0]?.items[0]?.asset_id).toBe(asset(96).asset_id);
    expect(viewer.snapshot().pages[0]?.items[0]?.asset_id).toBe(asset(144).asset_id);
  });

  it('uses all published group assets rather than the passenger match count', () => {
    const summary = {
      gallery: { total_asset_count: 5_000 },
      results: { match_count: 57 },
      search: { best_match_count: 45, possible_match_count: 12 },
    } as unknown as import('../../api/contracts').MyPhotosSummary;
    expect(myPhotosTotalForFilter(summary, 'best')).toBe(45);
    expect(myPhotosTotalForFilter(summary, 'possible')).toBe(12);
    expect(myPhotosTotalForFilter(summary, 'all')).toBe(5_000);
  });
});

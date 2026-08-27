import { ApiError } from '@/core/api/client';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';
import { sqliteValuesClause } from '@/core/storage/sqlite-batching';

import {
  MyPhotosAssetSchema,
  MyPhotosSummarySchema,
  type MatchFilter,
  type MyPhotosAsset,
  type MyPhotosPage,
  type MyPhotosSummary,
} from '../api/contracts';
import { getMyPhotosPage, getMyPhotosSummary } from '../api/my-photos-api';
import {
  GalleryPaginationError,
  MY_PHOTOS_MAX_PAGE_SIZE,
  MY_PHOTOS_MAX_RESIDENT_PAGES,
  MY_PHOTOS_PAGE_SIZE,
} from './gallery-window';
import type { MyPhotosContext } from './my-photos-context';

export type CachedResult<T> = Readonly<{
  value: T;
  source: 'network' | 'offline';
  cachedAt: string | null;
  partial: boolean;
}>;

type SummaryRow = Readonly<{ response_json: string; cached_at: string }>;
type PageRow = Readonly<{
  response_json: string;
  page_ordinal: number;
  item_ordinal: number;
}>;
type CursorRow = Readonly<{
  page_ordinal: number;
  request_cursor: string | null;
}>;
type CachedCursorRow = Readonly<{
  next_cursor: string | null;
  cached_at: string;
}>;
type CachedAssetCountRow = Readonly<{ cached_count: number }>;

export function isMyPhotosCachedMetadataPartial(
  summary: MyPhotosSummary,
  cachedAssetCount: number,
): boolean {
  if (!Number.isSafeInteger(cachedAssetCount) || cachedAssetCount < 0) {
    throw new Error('Cached My Photos asset count is invalid.');
  }
  const expected = summary.results.match_count > 0
    ? summary.results.match_count
    : summary.gallery.all_group_photos_enabled
      ? summary.gallery.total_asset_count
      : 0;
  return cachedAssetCount < expected;
}

function canUseOfflineFallback(error: unknown): boolean {
  if (error instanceof ApiError) return error.status === 0 || error.status >= 500 || error.code === 'NETWORK_ERROR';
  return error instanceof TypeError || (error instanceof Error && (
    error.name === 'AbortError' || error.name === 'TimeoutError'
  ));
}

export function assertMyPhotosSummaryContext(
  context: Pick<MyPhotosContext, 'tripId'>,
  summary: MyPhotosSummary,
): void {
  if (summary.group_id !== context.tripId) {
    throw new Error('My Photos summary belonged to another trip.');
  }
}

export function assertMyPhotosPageContext(
  page: MyPhotosPage,
  filter: MatchFilter,
  revision: number,
): void {
  if (page.filter !== filter) throw new GalleryPaginationError('FILTER_CHANGED');
  if (page.snapshot_revision !== revision) throw new GalleryPaginationError('REVISION_CHANGED');
}

export async function cacheMyPhotosSummary(
  context: MyPhotosContext,
  summary: MyPhotosSummary,
  assertActive: () => void,
  nowIso = new Date().toISOString(),
): Promise<void> {
  assertActive();
  const database = await openAccountDatabase(context.namespace);
  const serialized = JSON.stringify(MyPhotosSummarySchema.parse(summary));
  assertActive();
  await withAccountTransaction(database, async (transaction) => {
    assertActive();
    await transaction.runAsync(
      `INSERT INTO my_photos_summary_cache
        (account_namespace, trip_id, passenger_id, gallery_revision, response_json, cached_at)
       VALUES (?, ?, ?, ?, ?, ?)
       ON CONFLICT(account_namespace, trip_id, passenger_id) DO UPDATE SET
         gallery_revision = excluded.gallery_revision,
         response_json = excluded.response_json,
         cached_at = excluded.cached_at`,
      context.namespace,
      context.tripId,
      context.passengerId,
      summary.gallery.published_revision,
      serialized,
      nowIso,
    );
  });
  assertActive();
}

export async function loadCachedMyPhotosSummary(
  context: MyPhotosContext,
): Promise<CachedResult<MyPhotosSummary> | null> {
  const database = await openAccountDatabase(context.namespace);
  const row = await database.getFirstAsync<SummaryRow>(
    `SELECT response_json, cached_at
       FROM my_photos_summary_cache
      WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?`,
    context.namespace,
    context.tripId,
    context.passengerId,
  );
  if (!row) return null;
  try {
    const value = MyPhotosSummarySchema.parse(JSON.parse(row.response_json));
    assertMyPhotosSummaryContext(context, value);
    const expectedCachedAssets = value.results.match_count > 0
      ? value.results.match_count
      : value.gallery.all_group_photos_enabled ? value.gallery.total_asset_count : 0;
    const cachedAssets = expectedCachedAssets > 0
      ? await database.getFirstAsync<CachedAssetCountRow>(
          `SELECT COUNT(DISTINCT media_asset_id) AS cached_count
             FROM my_photos_page_cache
            WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
              AND gallery_revision = ?
              AND match_filter ${value.results.match_count > 0 ? "IN ('best', 'possible')" : "= 'all'"}`,
          context.namespace,
          context.tripId,
          context.passengerId,
          value.results.match_count > 0
            ? value.results.snapshot_revision
            : value.gallery.published_revision,
        )
      : null;
    return {
      value,
      source: 'offline',
      cachedAt: row.cached_at,
      partial: isMyPhotosCachedMetadataPartial(value, cachedAssets?.cached_count ?? 0),
    };
  } catch {
    await database.runAsync(
      `DELETE FROM my_photos_summary_cache
        WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?`,
      context.namespace,
      context.tripId,
      context.passengerId,
    );
    return null;
  }
}

export async function fetchMyPhotosSummary(
  context: MyPhotosContext,
  assertActive: () => void,
): Promise<CachedResult<MyPhotosSummary>> {
  try {
    const summary = await getMyPhotosSummary(context.tripId, context.signal);
    assertActive();
    assertMyPhotosSummaryContext(context, summary);
    await cacheMyPhotosSummary(context, summary, assertActive);
    assertActive();
    return { value: summary, source: 'network', cachedAt: null, partial: false };
  } catch (error) {
    assertActive();
    if (!canUseOfflineFallback(error)) throw error;
    const cached = await loadCachedMyPhotosSummary(context);
    assertActive();
    if (cached) return cached;
    throw error;
  }
}

/** Removes trip-owned private metadata after a server-confirmed feature
 * disable. The disabled summary is deliberately retained as the fail-closed
 * capability record and as the active observer that can receive re-enable
 * invalidation. */
export async function purgeMyPhotosPrivateTripData(
  context: MyPhotosContext,
  assertActive: () => void,
): Promise<void> {
  assertActive();
  const database = await openAccountDatabase(context.namespace);
  assertActive();
  await withAccountTransaction(database, async (transaction) => {
    assertActive();
    const owner = [context.namespace, context.tripId, context.passengerId] as const;
    await transaction.runAsync(
      `DELETE FROM my_photos_downloads
        WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?`,
      ...owner,
    );
    await transaction.runAsync(
      `DELETE FROM my_photos_download_batches
        WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?`,
      ...owner,
    );
    await transaction.runAsync(
      `DELETE FROM my_photos_reconciliation_state
        WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?`,
      ...owner,
    );
    await transaction.runAsync(
      `DELETE FROM my_photos_page_cache
        WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?`,
      ...owner,
    );
    await transaction.runAsync(
      `DELETE FROM my_photos_cursor_cache
        WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?`,
      ...owner,
    );
  });
  assertActive();
}

export async function cacheMyPhotosPage(
  context: MyPhotosContext,
  page: MyPhotosPage,
  pageOrdinal: number,
  requestCursor: string | null,
  direction: 'forward' | 'backward' | 'revisit',
  assertActive: () => void,
  nowIso = new Date().toISOString(),
): Promise<void> {
  if (!Number.isSafeInteger(pageOrdinal) || pageOrdinal < 0) throw new Error('Invalid page ordinal.');
  const database = await openAccountDatabase(context.namespace);
  assertActive();
  await withAccountTransaction(database, async (transaction) => {
    assertActive();
    await transaction.runAsync(
      `DELETE FROM my_photos_page_cache
        WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
          AND match_filter = ? AND gallery_revision <> ?`,
      context.namespace,
      context.tripId,
      context.passengerId,
      page.filter,
      page.snapshot_revision,
    );
    await transaction.runAsync(
      `DELETE FROM my_photos_cursor_cache
        WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
          AND match_filter = ? AND gallery_revision <> ?`,
      context.namespace,
      context.tripId,
      context.passengerId,
      page.filter,
      page.snapshot_revision,
    );
    const ordinalCursor = await transaction.getFirstAsync<CursorRow>(
      `SELECT page_ordinal, request_cursor
         FROM my_photos_cursor_cache
        WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
          AND gallery_revision = ? AND match_filter = ? AND page_ordinal = ?`,
      context.namespace,
      context.tripId,
      context.passengerId,
      page.snapshot_revision,
      page.filter,
      pageOrdinal,
    );
    if (ordinalCursor && ordinalCursor.request_cursor !== requestCursor) {
      throw new GalleryPaginationError('REPEATED_CURSOR');
    }
    if (requestCursor) {
      const cursorOwner = await transaction.getFirstAsync<CursorRow>(
        `SELECT page_ordinal, request_cursor
           FROM my_photos_cursor_cache
          WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
            AND gallery_revision = ? AND match_filter = ? AND request_cursor = ?`,
        context.namespace,
        context.tripId,
        context.passengerId,
        page.snapshot_revision,
        page.filter,
        requestCursor,
      );
      if (cursorOwner && cursorOwner.page_ordinal !== pageOrdinal) {
        throw new GalleryPaginationError('REPEATED_CURSOR');
      }
    }
    await transaction.runAsync(
      `INSERT INTO my_photos_cursor_cache
        (account_namespace, trip_id, passenger_id, gallery_revision, match_filter,
         page_ordinal, request_cursor, next_cursor, cached_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(account_namespace, trip_id, passenger_id, gallery_revision,
                   match_filter, page_ordinal) DO UPDATE SET
         next_cursor = excluded.next_cursor,
         cached_at = excluded.cached_at`,
      context.namespace,
      context.tripId,
      context.passengerId,
      page.snapshot_revision,
      page.filter,
      pageOrdinal,
      requestCursor,
      page.next_cursor,
      nowIso,
    );
    await transaction.runAsync(
      `DELETE FROM my_photos_page_cache
        WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
          AND gallery_revision = ? AND match_filter = ? AND page_ordinal = ?`,
      context.namespace,
      context.tripId,
      context.passengerId,
      page.snapshot_revision,
      page.filter,
      pageOrdinal,
    );
    if (page.items.length) {
      assertActive();
      await transaction.runAsync(
        `INSERT INTO my_photos_page_cache
          (account_namespace, trip_id, passenger_id, gallery_revision, match_filter,
           page_ordinal, item_ordinal, media_asset_id, response_json, cached_at)
         VALUES ${sqliteValuesClause(page.items.length, 10)}`,
        ...page.items.flatMap((asset, index) => [
          context.namespace,
          context.tripId,
          context.passengerId,
          page.snapshot_revision,
          page.filter,
          pageOrdinal,
          index,
          asset.asset_id,
          JSON.stringify(asset),
          nowIso,
        ]),
      );
    }
    await transaction.runAsync(
      `DELETE FROM my_photos_page_cache
        WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
          AND gallery_revision = ? AND match_filter = ? AND page_ordinal < ?`,
      context.namespace,
      context.tripId,
      context.passengerId,
      page.snapshot_revision,
      page.filter,
      direction === 'backward'
        ? pageOrdinal
        : Math.max(0, pageOrdinal - MY_PHOTOS_MAX_RESIDENT_PAGES + 1),
    );
    await transaction.runAsync(
      `DELETE FROM my_photos_page_cache
        WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
          AND gallery_revision = ? AND match_filter = ? AND page_ordinal > ?`,
      context.namespace,
      context.tripId,
      context.passengerId,
      page.snapshot_revision,
      page.filter,
      direction === 'backward'
        ? pageOrdinal + MY_PHOTOS_MAX_RESIDENT_PAGES - 1
        : pageOrdinal,
    );
  });
  assertActive();
}

export async function resolveMyPhotosPageRequestCursor(
  context: MyPhotosContext,
  filter: MatchFilter,
  revision: number,
  pageOrdinal: number,
  directCursor: string | null,
  lookupPersistedCursor: boolean,
): Promise<Readonly<{ cursor: string | null; revisit: boolean }>> {
  if (!Number.isSafeInteger(pageOrdinal) || pageOrdinal < 0 || pageOrdinal > 255) {
    throw new GalleryPaginationError('TRACKING_LIMIT_EXCEEDED');
  }
  if (pageOrdinal === 0 && directCursor !== null) {
    throw new GalleryPaginationError('REPEATED_CURSOR');
  }
  const database = await openAccountDatabase(context.namespace);
  const ordinalRow = await database.getFirstAsync<CursorRow>(
    `SELECT page_ordinal, request_cursor
       FROM my_photos_cursor_cache
      WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
        AND gallery_revision = ? AND match_filter = ? AND page_ordinal = ?`,
    context.namespace,
    context.tripId,
    context.passengerId,
    revision,
    filter,
    pageOrdinal,
  );
  if (lookupPersistedCursor) {
    if (!ordinalRow) throw new GalleryPaginationError('REPEATED_CURSOR');
    return { cursor: ordinalRow.request_cursor, revisit: true };
  }
  if (ordinalRow && ordinalRow.request_cursor !== directCursor) {
    throw new GalleryPaginationError('REPEATED_CURSOR');
  }
  if (directCursor) {
    const cursorOwner = await database.getFirstAsync<CursorRow>(
      `SELECT page_ordinal, request_cursor
         FROM my_photos_cursor_cache
        WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
          AND gallery_revision = ? AND match_filter = ? AND request_cursor = ?`,
      context.namespace,
      context.tripId,
      context.passengerId,
      revision,
      filter,
      directCursor,
    );
    if (cursorOwner && cursorOwner.page_ordinal !== pageOrdinal) {
      throw new GalleryPaginationError('REPEATED_CURSOR');
    }
  }
  return { cursor: directCursor, revisit: Boolean(ordinalRow) };
}

export async function loadCachedMyPhotosPage(
  context: MyPhotosContext,
  filter: MatchFilter,
  revision: number,
  totalCount: number,
  pageOrdinal: number,
): Promise<CachedResult<MyPhotosPage> | null> {
  const database = await openAccountDatabase(context.namespace);
  const cursor = await database.getFirstAsync<CachedCursorRow>(
    `SELECT next_cursor, cached_at
       FROM my_photos_cursor_cache
      WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
        AND gallery_revision = ? AND match_filter = ? AND page_ordinal = ?`,
    context.namespace,
    context.tripId,
    context.passengerId,
    revision,
    filter,
    pageOrdinal,
  );
  if (!cursor) return null;
  const rows = await database.getAllAsync<PageRow>(
    `SELECT response_json, page_ordinal, item_ordinal
       FROM my_photos_page_cache
      WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
        AND gallery_revision = ? AND match_filter = ? AND page_ordinal = ?
      ORDER BY item_ordinal ASC
      LIMIT ?`,
    context.namespace,
    context.tripId,
    context.passengerId,
    revision,
    filter,
    pageOrdinal,
    MY_PHOTOS_MAX_PAGE_SIZE,
  );
  const parsed: MyPhotosAsset[] = [];
  try {
    for (const row of rows) parsed.push(MyPhotosAssetSchema.parse(JSON.parse(row.response_json)));
  } catch {
    await withAccountTransaction(database, async (transaction) => {
      const parameters = [
        context.namespace,
        context.tripId,
        context.passengerId,
        revision,
        filter,
        pageOrdinal,
      ] as const;
      await transaction.runAsync(
        `DELETE FROM my_photos_page_cache
          WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
            AND gallery_revision = ? AND match_filter = ? AND page_ordinal = ?`,
        ...parameters,
      );
      await transaction.runAsync(
        `DELETE FROM my_photos_cursor_cache
          WHERE account_namespace = ? AND trip_id = ? AND passenger_id = ?
            AND gallery_revision = ? AND match_filter = ? AND page_ordinal = ?`,
        ...parameters,
      );
    });
    return null;
  }
  const page: MyPhotosPage = {
    snapshot_revision: revision,
    filter,
    items: parsed,
    next_cursor: cursor.next_cursor,
    page_size: parsed.length,
    total_count: totalCount,
  };
  return {
    value: page,
    source: 'offline',
    cachedAt: cursor.cached_at,
    partial: pageOrdinal > 0 || cursor.next_cursor !== null || parsed.length < totalCount,
  };
}

export async function fetchMyPhotosPage(
  context: MyPhotosContext,
  filter: MatchFilter,
  cursor: string | null,
  pageOrdinal: number,
  revision: number,
  totalCount: number,
  assertActive: () => void,
  direction: 'forward' | 'backward' | 'revisit' = 'forward',
  validatePage?: (page: MyPhotosPage) => void,
): Promise<CachedResult<MyPhotosPage>> {
  try {
    const page = await getMyPhotosPage(context.tripId, filter, {
      cursor, limit: MY_PHOTOS_PAGE_SIZE, signal: context.signal,
    });
    assertActive();
    assertMyPhotosPageContext(page, filter, revision);
    validatePage?.(page);
    await cacheMyPhotosPage(context, page, pageOrdinal, cursor, direction, assertActive);
    assertActive();
    return { value: page, source: 'network', cachedAt: null, partial: false };
  } catch (error) {
    assertActive();
    if (!canUseOfflineFallback(error)) throw error;
    const cached = await loadCachedMyPhotosPage(
      context,
      filter,
      revision,
      totalCount,
      pageOrdinal,
    );
    assertActive();
    if (cached) return cached;
    throw error;
  }
}

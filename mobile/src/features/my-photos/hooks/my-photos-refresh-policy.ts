import { ApiError } from '@/core/api/client';

import type { MyPhotosSummary } from '../api/contracts';

export const MY_PHOTOS_SEARCHING_MIN_REFRESH_MS = 5_000;
export const MY_PHOTOS_SEARCHING_MAX_REFRESH_MS = 10_000;
export const MY_PHOTOS_QUEUED_MIN_REFRESH_MS = 10_000;
export const MY_PHOTOS_QUEUED_MAX_REFRESH_MS = 20_000;
export const MY_PHOTOS_PROCESSING_MIN_REFRESH_MS = 15_000;
export const MY_PHOTOS_PROCESSING_MAX_REFRESH_MS = 30_000;
export const MY_PHOTOS_MAX_FAILURE_REFRESH_MS = 60_000;
export const MY_PHOTOS_MAX_SERVER_BACKOFF_MS = 5 * 60_000;

type MyPhotosRefreshInput = Readonly<{
  routeFocused: boolean;
  experienceState: MyPhotosSummary['experience_state'] | null;
  searchStatus: NonNullable<MyPhotosSummary['search']>['status'] | null;
  failureCount?: number;
  error?: unknown;
  randomValue?: number;
}>;

function activeRefreshWindow(input: MyPhotosRefreshInput): Readonly<{
  minimumMs: number;
  maximumMs: number;
}> | null {
  if (input.searchStatus === 'searching' || input.experienceState === 'searching') {
    return {
      minimumMs: MY_PHOTOS_SEARCHING_MIN_REFRESH_MS,
      maximumMs: MY_PHOTOS_SEARCHING_MAX_REFRESH_MS,
    };
  }
  if (input.searchStatus === 'queued' || input.experienceState === 'search_queued') {
    return {
      minimumMs: MY_PHOTOS_QUEUED_MIN_REFRESH_MS,
      maximumMs: MY_PHOTOS_QUEUED_MAX_REFRESH_MS,
    };
  }
  if (
    input.experienceState === 'gallery_processing'
    || input.experienceState === 'gallery_indexing'
    || input.experienceState === 'matches_preparing'
  ) {
    return {
      minimumMs: MY_PHOTOS_PROCESSING_MIN_REFRESH_MS,
      maximumMs: MY_PHOTOS_PROCESSING_MAX_REFRESH_MS,
    };
  }
  return null;
}

/**
 * Realtime trip reconciliation may invalidate the summary immediately. This
 * single focused query is the degraded repair lane when a hint is missed or a
 * background job has not yet emitted one; no second progress poll is allowed.
 */
export function myPhotosSummaryRefreshInterval(input: MyPhotosRefreshInput): number | false {
  if (!input.routeFocused) return false;
  const window = activeRefreshWindow(input);
  if (!window) return false;

  const failures = Math.min(2, Math.max(0, Math.floor(input.failureCount ?? 0)));
  const multiplier = 2 ** failures;
  const minimumMs = Math.min(MY_PHOTOS_MAX_FAILURE_REFRESH_MS, window.minimumMs * multiplier);
  const maximumMs = Math.min(MY_PHOTOS_MAX_FAILURE_REFRESH_MS, window.maximumMs * multiplier);
  const boundedRandom = Math.min(1, Math.max(0, input.randomValue ?? Math.random()));
  const jitteredInterval = Math.round(
    minimumMs + (maximumMs - minimumMs) * boundedRandom,
  );

  if (!(input.error instanceof ApiError) || input.error.retryAfterSeconds === null) {
    return jitteredInterval;
  }
  return Math.max(
    jitteredInterval,
    Math.min(
      MY_PHOTOS_MAX_SERVER_BACKOFF_MS,
      Math.max(0, input.error.retryAfterSeconds * 1_000),
    ),
  );
}

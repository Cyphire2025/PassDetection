import { ApiError } from '@/core/api/client';

import {
  MY_PHOTOS_PROCESSING_MAX_REFRESH_MS,
  MY_PHOTOS_PROCESSING_MIN_REFRESH_MS,
  MY_PHOTOS_QUEUED_MAX_REFRESH_MS,
  MY_PHOTOS_QUEUED_MIN_REFRESH_MS,
  MY_PHOTOS_SEARCHING_MAX_REFRESH_MS,
  MY_PHOTOS_SEARCHING_MIN_REFRESH_MS,
  myPhotosSummaryRefreshInterval,
} from '../my-photos-refresh-policy';

const inactive = {
  experienceState: 'matches_ready' as const,
  searchStatus: 'complete' as const,
};

test('stops the only My Photos repair query when unfocused or terminal', () => {
  expect(myPhotosSummaryRefreshInterval({
    routeFocused: false,
    experienceState: 'matches_preparing',
    searchStatus: 'searching',
    randomValue: 0,
  })).toBe(false);
  expect(myPhotosSummaryRefreshInterval({
    routeFocused: true,
    ...inactive,
    randomValue: 0,
  })).toBe(false);
});

test('adapts one jittered summary query to searching, queued, and processing states', () => {
  expect(myPhotosSummaryRefreshInterval({
    routeFocused: true,
    experienceState: 'matches_preparing',
    searchStatus: 'searching',
    randomValue: 0,
  })).toBe(MY_PHOTOS_SEARCHING_MIN_REFRESH_MS);
  expect(myPhotosSummaryRefreshInterval({
    routeFocused: true,
    experienceState: 'matches_preparing',
    searchStatus: 'searching',
    randomValue: 1,
  })).toBe(MY_PHOTOS_SEARCHING_MAX_REFRESH_MS);
  expect(myPhotosSummaryRefreshInterval({
    routeFocused: true,
    experienceState: 'matches_preparing',
    searchStatus: 'queued',
    randomValue: 0,
  })).toBe(MY_PHOTOS_QUEUED_MIN_REFRESH_MS);
  expect(myPhotosSummaryRefreshInterval({
    routeFocused: true,
    experienceState: 'gallery_indexing',
    searchStatus: null,
    randomValue: 1,
  })).toBe(MY_PHOTOS_PROCESSING_MAX_REFRESH_MS);
  expect(MY_PHOTOS_QUEUED_MAX_REFRESH_MS).toBeLessThanOrEqual(
    MY_PHOTOS_PROCESSING_MAX_REFRESH_MS,
  );
  expect(MY_PHOTOS_PROCESSING_MIN_REFRESH_MS).toBeGreaterThan(
    MY_PHOTOS_SEARCHING_MIN_REFRESH_MS,
  );
});

test('backs off after failures and honors a longer bounded Retry-After', () => {
  expect(myPhotosSummaryRefreshInterval({
    routeFocused: true,
    experienceState: 'gallery_processing',
    searchStatus: null,
    failureCount: 1,
    randomValue: 0,
  })).toBe(30_000);
  expect(myPhotosSummaryRefreshInterval({
    routeFocused: true,
    experienceState: 'matches_preparing',
    searchStatus: 'searching',
    error: new ApiError('Slow down', 429, 'RATE_LIMITED', 90),
    randomValue: 0,
  })).toBe(90_000);
});

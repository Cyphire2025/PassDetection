export type VirtualizedListBudget = Readonly<{
  initialNumToRender: number;
  maxToRenderPerBatch: number;
  updateCellsBatchingPeriod: number;
  windowSize: number;
}>;

function listBudget(
  initialNumToRender: number,
  maxToRenderPerBatch: number,
  updateCellsBatchingPeriod: number,
  windowSize: number,
): VirtualizedListBudget {
  return Object.freeze({
    initialNumToRender,
    maxToRenderPerBatch,
    updateCellsBatchingPeriod,
    windowSize,
  });
}

/**
 * Stable module-level objects prevent list configuration identity churn. The
 * profiles preserve the values already used by the UI; they make those limits
 * reviewable and regression-testable without claiming measured device FPS.
 */
export const MOBILE_LIST_WINDOWING = Object.freeze({
  picker: listBudget(6, 8, 50, 5),
  compact: listBudget(8, 12, 50, 5),
  compactInteractive: listBudget(8, 12, 35, 5),
  standard: listBudget(10, 12, 50, 7),
  interactive: listBudget(10, 12, 35, 7),
  feed: listBudget(10, 14, 50, 7),
  moderateRoster: listBudget(12, 16, 50, 7),
  denseRoster: listBudget(16, 24, 35, 7),
  detail: listBudget(18, 24, 35, 7),
  photoGrid: listBudget(18, 18, 40, 7),
});

/** Reviewable My Photos client budgets. Physical-device release profiling is
 * still required before these become evidence of native rendering latency. */
export const MY_PHOTOS_CLIENT_BUDGET = Object.freeze({
  columns: 3,
  pageSize: 48,
  maximumServerPageSize: 60,
  maximumResidentPages: 4,
  maximumResidentMetadataItems: 240,
  nextPagePrefetchThreshold: 0.6,
  targetFirstContentMs: 1_500,
});

export const MOBILE_STATIC_ASSET_BUDGET = Object.freeze({
  bundledImageCount: 12,
  bundledImageBytes: 4 * 1024 * 1024,
  singleImageBytes: 1_750_000,
  singleImagePixels: 1_750_000,
});

export const MOBILE_REQUEST_BUDGET = Object.freeze({
  minimumForegroundPollingMs: 8_000,
  minimumLifecycleFallbackMs: 5 * 60_000,
  maximumAutomaticQueryRetries: 2,
});

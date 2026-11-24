export const PASSPORT_LIVE_THRESHOLDS = {
  sampleWidth: 320,
  sampleHeight: 200,
  guideContextMarginRatio: 0.1,
  edgePositionToleranceRatio: 0.075,
  edgeStepContrast: 8,
  maximumSearchSlope: 0.32,
  searchSlopeStep: 0.04,
  strongEdgeSupport: 0.72,
  strongSegmentCoverage: 0.75,
  strongPolarityConsistency: 0.7,
  strongAverageContrast: 14,
  plausibleEdgeSupport: 0.28,
  plausibleSegmentCoverage: 0.5,
  plausiblePolarityConsistency: 0.62,
  plausibleAverageContrast: 8,
  minimumStrongEdges: 3,
  minimumDocumentSpanRatio: 0.68,
  maximumDocumentSpanRatio: 0.94,
  minimumDocumentAreaRatio: 0.5,
  maximumDocumentAreaRatio: 0.84,
  maximumCenterOffsetRatio: 0.075,
  maximumReadySkewDegrees: 8,
  maximumOppositeEdgeAngleDelta: 7,
  maximumAxisAngleDelta: 8,
  detailColumns: 4,
  detailRows: 3,
  detailGradient: 26,
  minimumDetailEdgeRatio: 0.045,
  minimumDetailDeviation: 8,
  minimumDetailedTileRatio: 7 / 12,
  minimumDetailedRowCoverage: 2 / 3,
  extremeDarkLuminance: 22,
  extremeBrightLuminance: 248,
  extremeDarkMean: 30,
  extremeBrightMean: 241,
  extremePixelRatio: 0.72,
} as const;

export const SAMPLE_WIDTH = PASSPORT_LIVE_THRESHOLDS.sampleWidth;

export const SAMPLE_HEIGHT = PASSPORT_LIVE_THRESHOLDS.sampleHeight;

export const GUIDE_CONTEXT_MARGIN_RATIO = (
  PASSPORT_LIVE_THRESHOLDS.guideContextMarginRatio
);

export const GUIDE_EDGE_MIN_RATIO = (
  GUIDE_CONTEXT_MARGIN_RATIO / (1 + GUIDE_CONTEXT_MARGIN_RATIO * 2)
);

export const GUIDE_EDGE_MAX_RATIO = 1 - GUIDE_EDGE_MIN_RATIO;

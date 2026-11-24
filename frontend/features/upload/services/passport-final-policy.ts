export const PASSPORT_FINAL_THRESHOLDS = {
  analysisMaxWidth: 600,
  extremeDarkMean: 38,
  extremeDarkRatio: 0.72,
  extremeBrightMean: 235,
  extremeBrightRatio: 0.58,
  hardMinimumCoverage: 0.46,
  borderlineMinimumCoverage: 0.62,
  hardMinimumAspectRatio: 1.0,
  hardMaximumAspectRatio: 2.05,
  borderlineMinimumAspectRatio: 1.08,
  borderlineMaximumAspectRatio: 1.88,
  severeSharpness: 16,
  severeDetailDensity: 0.018,
  softSharpness: 34,
  softDetailDensity: 0.036,
  severeTextContrast: 10,
  severeRegionalGlare: 0.17,
  borderlineRegionalGlare: 0.055,
  preferredMinimumWidth: 900,
  darkUiBandRatio: 0.58,
  brightUiBandRatio: 0.72,
  uiBandMeanDifference: 42,
  bezelDarkRatio: 0.54,
  documentBoundarySupport: 0.48,
  documentBoundaryOuterInsetRatio: 0.24,
} as const;

export const FRONT_REGIONS = {
  overall: { left: 0.02, top: 0.03, right: 0.98, bottom: 0.97 },
  mainDetails: { left: 0.34, top: 0.08, right: 0.97, bottom: 0.70 },
  lowerTextBand: { left: 0.04, top: 0.66, right: 0.97, bottom: 0.96 },
  portrait: { left: 0.03, top: 0.08, right: 0.38, bottom: 0.70 },
} as const;

export const BACK_REGIONS = {
  overall: { left: 0.02, top: 0.03, right: 0.98, bottom: 0.97 },
  mainDetails: { left: 0.10, top: 0.12, right: 0.90, bottom: 0.66 },
  lowerTextBand: { left: 0.08, top: 0.55, right: 0.92, bottom: 0.92 },
  portrait: { left: 0.18, top: 0.20, right: 0.82, bottom: 0.82 },
} as const;

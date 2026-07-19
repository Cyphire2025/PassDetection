import type { CameraValidationOutcome } from "./camera-quality-policy";
import type { PassportPageSide } from "./passport-frame-detector";

export type PassportFinalQualityReason =
  | "ready"
  | "invalid_image"
  | "extreme_exposure"
  | "passport_too_small"
  | "document_area_missing"
  | "text_unreadable"
  | "severe_glare"
  | "obvious_screen_recapture"
  | "slightly_soft"
  | "small_reflection"
  | "lower_resolution"
  | "weak_screen_suspicion";

export interface PassportRegionQuality {
  sharpness: number;
  detailDensity: number;
  contrast: number;
  meanLuminance: number;
  darkPixelRatio: number;
  clippedHighlightRatio: number;
}

export interface PassportFinalQualityMetrics {
  overall: PassportRegionQuality;
  mainDetails: PassportRegionQuality;
  lowerTextBand: PassportRegionQuality;
  portrait: PassportRegionQuality;
  effectiveCoverage: number;
  strongBoundaryCount: number;
  missingBoundaryLikely: boolean;
  obviousScreenSignals: number;
  weakScreenSignals: number;
  sourceWidth: number;
  sourceHeight: number;
}

export interface PassportFinalQualityResult {
  outcome: CameraValidationOutcome;
  reason: PassportFinalQualityReason;
  message: string;
  confirmationPrompt: string | null;
  metrics: PassportFinalQualityMetrics;
}

interface NormalizedRegion {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

interface ScreenEvidence {
  obviousSignals: number;
  weakSignals: number;
}

interface DocumentBoundaryEstimate {
  coverage: number;
  strongBoundaryCount: number;
  missingBoundaryLikely: boolean;
}

const PASSPORT_FINAL_THRESHOLDS = {
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

const FRONT_REGIONS = {
  overall: { left: 0.02, top: 0.03, right: 0.98, bottom: 0.97 },
  mainDetails: { left: 0.34, top: 0.08, right: 0.97, bottom: 0.70 },
  lowerTextBand: { left: 0.04, top: 0.66, right: 0.97, bottom: 0.96 },
  portrait: { left: 0.03, top: 0.08, right: 0.38, bottom: 0.70 },
} as const;

const BACK_REGIONS = {
  overall: { left: 0.02, top: 0.03, right: 0.98, bottom: 0.97 },
  mainDetails: { left: 0.10, top: 0.12, right: 0.90, bottom: 0.66 },
  lowerTextBand: { left: 0.08, top: 0.55, right: 0.92, bottom: 0.92 },
  portrait: { left: 0.18, top: 0.20, right: 0.82, bottom: 0.82 },
} as const;

/**
 * Decodes the exact JPEG that will be uploaded and validates those encoded
 * pixels. Live-frame scores are deliberately not accepted as a substitute.
 */
export async function validatePassportFinalFile(
  file: File,
  pageSide: PassportPageSide,
): Promise<PassportFinalQualityResult> {
  const decoded = await decodeImageFile(file);
  try {
    const scale = Math.min(
      1,
      PASSPORT_FINAL_THRESHOLDS.analysisMaxWidth / decoded.width,
    );
    const width = Math.max(80, Math.round(decoded.width * scale));
    const height = Math.max(50, Math.round(decoded.height * scale));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) {
      return invalidResult(decoded.width, decoded.height);
    }
    context.drawImage(decoded.image, 0, 0, width, height);
    const pixels = context.getImageData(0, 0, width, height).data;
    return analyzePassportFinalPixels(
      pixels,
      width,
      height,
      pageSide,
      decoded.width,
      decoded.height,
    );
  } finally {
    decoded.close();
  }
}

export function analyzePassportFinalPixels(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
  pageSide: PassportPageSide,
  sourceWidth = width,
  sourceHeight = height,
): PassportFinalQualityResult {
  if (
    width < 80
    || height < 50
    || pixels.length < width * height * 4
  ) {
    return invalidResult(sourceWidth, sourceHeight);
  }

  const gray = toGrayscale(pixels, width, height);
  const regions = pageSide === "front" ? FRONT_REGIONS : BACK_REGIONS;
  const overall = analyzeRegion(pixels, gray, width, height, regions.overall);
  const mainDetails = analyzeRegion(
    pixels,
    gray,
    width,
    height,
    regions.mainDetails,
  );
  const lowerTextBand = analyzeRegion(
    pixels,
    gray,
    width,
    height,
    regions.lowerTextBand,
  );
  const portrait = analyzeRegion(
    pixels,
    gray,
    width,
    height,
    regions.portrait,
  );
  const boundaryEstimate = estimateDocumentCoverage(
    gray,
    width,
    height,
  );
  const effectiveCoverage = boundaryEstimate.coverage;
  const screenEvidence = detectScreenEvidence(
    pixels,
    gray,
    width,
    height,
    overall,
  );
  const metrics: PassportFinalQualityMetrics = {
    overall,
    mainDetails,
    lowerTextBand,
    portrait,
    effectiveCoverage: roundMetric(effectiveCoverage),
    strongBoundaryCount: boundaryEstimate.strongBoundaryCount,
    missingBoundaryLikely: boundaryEstimate.missingBoundaryLikely,
    obviousScreenSignals: screenEvidence.obviousSignals,
    weakScreenSignals: screenEvidence.weakSignals,
    sourceWidth,
    sourceHeight,
  };

  if (isExtremeExposure(overall)) {
    return result(
      "hard_failure",
      "extreme_exposure",
      overall.meanLuminance < PASSPORT_FINAL_THRESHOLDS.extremeDarkMean
        ? "The captured passport is extremely dark. Move into brighter, even lighting and retake it."
        : "The captured passport is severely overexposed. Reduce the light and retake it.",
      metrics,
    );
  }

  const aspectRatio = sourceWidth / Math.max(1, sourceHeight);
  if (
    effectiveCoverage < PASSPORT_FINAL_THRESHOLDS.hardMinimumCoverage
  ) {
    return result(
      "hard_failure",
      boundaryEstimate.missingBoundaryLikely
        ? "document_area_missing"
        : "passport_too_small",
      boundaryEstimate.missingBoundaryLikely
        ? "A major part of the passport page appears to be outside the captured image. Keep the full page inside the guide and retake it."
        : "The passport occupies too little of the captured image. Move closer, keep the full page visible, and retake it.",
      metrics,
    );
  }
  if (
    aspectRatio < PASSPORT_FINAL_THRESHOLDS.hardMinimumAspectRatio
    || aspectRatio > PASSPORT_FINAL_THRESHOLDS.hardMaximumAspectRatio
  ) {
    return result(
      "hard_failure",
      "document_area_missing",
      "A major part of the passport page appears to be missing. Keep the full page inside the guide and retake it.",
      metrics,
    );
  }
  if (screenEvidence.obviousSignals >= 1) {
    return result(
      "hard_failure",
      "obvious_screen_recapture",
      "A phone bezel or screen interface is visible. Photograph the physical passport page directly and retake it.",
      metrics,
    );
  }
  if (
    mainDetails.clippedHighlightRatio
      >= PASSPORT_FINAL_THRESHOLDS.severeRegionalGlare
    || lowerTextBand.clippedHighlightRatio
      >= PASSPORT_FINAL_THRESHOLDS.severeRegionalGlare
  ) {
    return result(
      "hard_failure",
      "severe_glare",
      "Severe glare covers the passport details. Tilt the physical passport away from the light and retake it.",
      metrics,
    );
  }

  const mainAreaMissing = isRegionEffectivelyBlank(mainDetails);
  const lowerAreaMissing = isRegionEffectivelyBlank(lowerTextBand);
  const portraitAreaMissing = pageSide === "front"
    && isRegionEffectivelyBlank(portrait);
  if (
    (mainAreaMissing && lowerTextBand.detailDensity >= 0.05)
    || (lowerAreaMissing && mainDetails.detailDensity >= 0.05)
    || (portraitAreaMissing && mainDetails.detailDensity >= 0.05)
  ) {
    return result(
      "hard_failure",
      "document_area_missing",
      portraitAreaMissing
        ? "The passport portrait area is missing from the captured image. Keep the full information page inside the guide and retake it."
        : "A major passport details area is missing from the captured image. Keep the full page inside the guide and retake it.",
      metrics,
    );
  }

  const mainSeverelyUnreadable = isSeverelyUnreadable(mainDetails);
  const lowerSeverelyUnreadable = isSeverelyUnreadable(lowerTextBand);
  if (mainSeverelyUnreadable && lowerSeverelyUnreadable) {
    return result(
      "hard_failure",
      "text_unreadable",
      pageSide === "front"
        ? "The passport number and lower text lines are too blurred to read. Hold steady, let the camera focus, and retake it."
        : "The important details on the passport back page are too blurred to read. Hold steady, let the camera focus, and retake it.",
      metrics,
    );
  }

  const borderlineReasons: PassportFinalQualityReason[] = [];
  if (
    effectiveCoverage
      < PASSPORT_FINAL_THRESHOLDS.borderlineMinimumCoverage
    || boundaryEstimate.missingBoundaryLikely
    || aspectRatio < PASSPORT_FINAL_THRESHOLDS.borderlineMinimumAspectRatio
    || aspectRatio > PASSPORT_FINAL_THRESHOLDS.borderlineMaximumAspectRatio
  ) {
    borderlineReasons.push("document_area_missing");
  }
  if (
    isSoft(mainDetails)
    || isSoft(lowerTextBand)
    || mainSeverelyUnreadable
    || lowerSeverelyUnreadable
  ) {
    borderlineReasons.push("slightly_soft");
  }
  const regionalGlare = Math.max(
    mainDetails.clippedHighlightRatio,
    lowerTextBand.clippedHighlightRatio,
  );
  if (
    regionalGlare
      >= PASSPORT_FINAL_THRESHOLDS.borderlineRegionalGlare
  ) {
    borderlineReasons.push("small_reflection");
  }
  if (
    sourceWidth < PASSPORT_FINAL_THRESHOLDS.preferredMinimumWidth
  ) {
    borderlineReasons.push("lower_resolution");
  }
  if (screenEvidence.weakSignals >= 1) {
    borderlineReasons.push("weak_screen_suspicion");
  }

  if (borderlineReasons.length > 0) {
    const reason = borderlineReasons[0];
    return result(
      "borderline",
      reason,
      borderlineMessage(reason, pageSide),
      metrics,
      pageSide === "front"
        ? "Can you clearly read the passport number and the two lines at the bottom?"
        : "Can you clearly read the address and other printed details on this passport page?",
    );
  }

  return result(
    "pass",
    "ready",
    "The captured passport image is clear enough to continue.",
    metrics,
  );
}

function analyzeRegion(
  pixels: Uint8ClampedArray,
  gray: Uint8Array,
  width: number,
  height: number,
  region: NormalizedRegion,
): PassportRegionQuality {
  const bounds = pixelBounds(region, width, height);
  let samples = 0;
  let luminanceTotal = 0;
  let luminanceSquaredTotal = 0;
  let darkPixels = 0;
  let clippedHighlights = 0;
  let edgePixels = 0;
  let laplacianSamples = 0;
  let laplacianTotal = 0;
  let laplacianSquaredTotal = 0;

  for (let y = bounds.top; y <= bounds.bottom; y += 1) {
    for (let x = bounds.left; x <= bounds.right; x += 1) {
      const index = y * width + x;
      const luminance = gray[index];
      samples += 1;
      luminanceTotal += luminance;
      luminanceSquaredTotal += luminance * luminance;
      if (luminance < 34) darkPixels += 1;
      const rgbaOffset = index * 4;
      const channelMinimum = Math.min(
        pixels[rgbaOffset],
        pixels[rgbaOffset + 1],
        pixels[rgbaOffset + 2],
      );
      if (luminance > 244 && channelMinimum > 232) {
        clippedHighlights += 1;
      }
      if (
        x <= bounds.left
        || x >= bounds.right
        || y <= bounds.top
        || y >= bounds.bottom
      ) {
        continue;
      }
      const horizontal = Math.abs(gray[index + 1] - gray[index - 1]);
      const vertical = Math.abs(
        gray[index + width] - gray[index - width],
      );
      if (horizontal + vertical >= 34) edgePixels += 1;
      const laplacian = (
        gray[index - 1]
        + gray[index + 1]
        + gray[index - width]
        + gray[index + width]
        - 4 * luminance
      );
      laplacianSamples += 1;
      laplacianTotal += laplacian;
      laplacianSquaredTotal += laplacian * laplacian;
    }
  }

  const meanLuminance = luminanceTotal / Math.max(1, samples);
  const contrast = Math.sqrt(Math.max(
    0,
    luminanceSquaredTotal / Math.max(1, samples)
      - meanLuminance * meanLuminance,
  ));
  const laplacianMean = laplacianTotal / Math.max(1, laplacianSamples);
  const sharpness = Math.max(
    0,
    laplacianSquaredTotal / Math.max(1, laplacianSamples)
      - laplacianMean * laplacianMean,
  );

  return {
    sharpness: roundMetric(sharpness),
    detailDensity: roundMetric(
      edgePixels / Math.max(1, laplacianSamples),
    ),
    contrast: roundMetric(contrast),
    meanLuminance: roundMetric(meanLuminance),
    darkPixelRatio: roundMetric(darkPixels / Math.max(1, samples)),
    clippedHighlightRatio: roundMetric(
      clippedHighlights / Math.max(1, samples),
    ),
  };
}

function estimateDocumentCoverage(
  gray: Uint8Array,
  width: number,
  height: number,
): DocumentBoundaryEstimate {
  const left = strongestVerticalBoundary(gray, width, height, "left");
  const right = strongestVerticalBoundary(gray, width, height, "right");
  const top = strongestHorizontalBoundary(gray, width, height, "top");
  const bottom = strongestHorizontalBoundary(gray, width, height, "bottom");
  const minimumSupport = PASSPORT_FINAL_THRESHOLDS.documentBoundarySupport;
  const boundaries = [
    {
      boundary: left,
      outerInset: left.position / Math.max(1, width - 1),
    },
    {
      boundary: right,
      outerInset: (width - 1 - right.position) / Math.max(1, width - 1),
    },
    {
      boundary: top,
      outerInset: top.position / Math.max(1, height - 1),
    },
    {
      boundary: bottom,
      outerInset: (height - 1 - bottom.position) / Math.max(1, height - 1),
    },
  ];
  const strongBoundaries = boundaries.filter(
    ({ boundary }) => boundary.support >= minimumSupport,
  );
  const strongBoundaryCount = strongBoundaries.length;
  const missingBoundaryLikely = strongBoundaryCount === 3
    && strongBoundaries.every(({ outerInset }) => (
      outerInset <= (
        PASSPORT_FINAL_THRESHOLDS.documentBoundaryOuterInsetRatio
      )
    ));
  // Text columns and portrait edges can look like partial page boundaries.
  // Four agreeing edges provide a coverage estimate. Three are only used when
  // each detected edge sits in its expected outer zone; that evidence is kept
  // borderline unless the visible document area is definitively too small.
  if (strongBoundaryCount < 4 && !missingBoundaryLikely) {
    return {
      coverage: 1,
      strongBoundaryCount,
      missingBoundaryLikely: false,
    };
  }

  const estimatedLeft = left.support >= minimumSupport ? left.position : 0;
  const estimatedRight = right.support >= minimumSupport
    ? right.position
    : width - 1;
  const estimatedTop = top.support >= minimumSupport ? top.position : 0;
  const estimatedBottom = bottom.support >= minimumSupport
    ? bottom.position
    : height - 1;
  return {
    coverage: clamp01(
      ((estimatedRight - estimatedLeft + 1) / width)
        * ((estimatedBottom - estimatedTop + 1) / height),
    ),
    strongBoundaryCount,
    missingBoundaryLikely,
  };
}

function strongestVerticalBoundary(
  gray: Uint8Array,
  width: number,
  height: number,
  side: "left" | "right",
): { position: number; support: number } {
  const start = side === "left" ? 1 : Math.round(width * 0.72);
  const end = side === "left" ? Math.round(width * 0.28) : width - 2;
  let best = { position: side === "left" ? 0 : width - 1, support: 0 };
  for (let x = start; x <= end; x += 1) {
    let supported = 0;
    let samples = 0;
    for (let y = Math.round(height * 0.06); y < height * 0.94; y += 3) {
      const index = y * width + x;
      if (Math.abs(gray[index + 1] - gray[index - 1]) >= 24) {
        supported += 1;
      }
      samples += 1;
    }
    const support = supported / Math.max(1, samples);
    if (support > best.support) best = { position: x, support };
  }
  return best;
}

function strongestHorizontalBoundary(
  gray: Uint8Array,
  width: number,
  height: number,
  side: "top" | "bottom",
): { position: number; support: number } {
  const start = side === "top" ? 1 : Math.round(height * 0.72);
  const end = side === "top" ? Math.round(height * 0.28) : height - 2;
  let best = { position: side === "top" ? 0 : height - 1, support: 0 };
  for (let y = start; y <= end; y += 1) {
    let supported = 0;
    let samples = 0;
    for (let x = Math.round(width * 0.05); x < width * 0.95; x += 3) {
      const index = y * width + x;
      if (
        Math.abs(gray[index + width] - gray[index - width]) >= 24
      ) {
        supported += 1;
      }
      samples += 1;
    }
    const support = supported / Math.max(1, samples);
    if (support > best.support) best = { position: y, support };
  }
  return best;
}

function detectScreenEvidence(
  pixels: Uint8ClampedArray,
  gray: Uint8Array,
  width: number,
  height: number,
  overall: PassportRegionQuality,
): ScreenEvidence {
  const top = bandMetrics(pixels, gray, width, height, {
    left: 0.04,
    top: 0,
    right: 0.96,
    bottom: 0.075,
  });
  const bottom = bandMetrics(pixels, gray, width, height, {
    left: 0.04,
    top: 0.925,
    right: 0.96,
    bottom: 1,
  });
  const left = bandMetrics(pixels, gray, width, height, {
    left: 0,
    top: 0.06,
    right: 0.055,
    bottom: 0.94,
  });
  const right = bandMetrics(pixels, gray, width, height, {
    left: 0.945,
    top: 0.06,
    right: 1,
    bottom: 0.94,
  });
  const topCenter = bandMetrics(pixels, gray, width, height, {
    left: 0.42,
    top: 0,
    right: 0.58,
    bottom: 0.09,
  });
  const topSides = bandMetrics(pixels, gray, width, height, {
    left: 0.08,
    top: 0,
    right: 0.36,
    bottom: 0.09,
  });

  const darkBands = [top, bottom].filter(
    (band) => band.darkPixelRatio
      >= PASSPORT_FINAL_THRESHOLDS.darkUiBandRatio,
  ).length;
  const darkSideBorders = [left, right].filter(
    (band) => band.darkPixelRatio
      >= PASSPORT_FINAL_THRESHOLDS.bezelDarkRatio,
  ).length;
  const strongUiBar = [top, bottom].some((band) => (
    Math.abs(band.meanLuminance - overall.meanLuminance)
      >= PASSPORT_FINAL_THRESHOLDS.uiBandMeanDifference
    && (
      band.darkPixelRatio >= PASSPORT_FINAL_THRESHOLDS.darkUiBandRatio
      || band.clippedHighlightRatio
        >= PASSPORT_FINAL_THRESHOLDS.brightUiBandRatio
    )
    && band.detailDensity >= 0.025
  ));
  const structuredNeutralUiBar = (
    Math.abs(top.meanLuminance - overall.meanLuminance) >= 24
    && top.meanLuminance >= 45
    && top.meanLuminance <= 215
    && top.contrast >= 40
    && top.detailDensity >= 0.08
  );
  const centeredNotch = topCenter.darkPixelRatio >= 0.42
    && topSides.darkPixelRatio <= 0.18
    && topCenter.meanLuminance + 45 < topSides.meanLuminance;
  const obviousBezel = (
    darkBands >= 1
    && darkSideBorders >= 1
    && overall.meanLuminance >= 72
  );

  let obviousSignals = 0;
  if (strongUiBar || structuredNeutralUiBar) obviousSignals += 1;
  if (centeredNotch) obviousSignals += 1;
  if (obviousBezel) obviousSignals += 1;

  let weakSignals = 0;
  if (darkBands === 1 && !strongUiBar) weakSignals += 1;
  if (darkSideBorders === 1 && !obviousBezel) weakSignals += 1;
  if (
    overall.clippedHighlightRatio > 0.12
    && overall.detailDensity < 0.035
  ) {
    weakSignals += 1;
  }
  return { obviousSignals, weakSignals };
}

function bandMetrics(
  pixels: Uint8ClampedArray,
  gray: Uint8Array,
  width: number,
  height: number,
  region: NormalizedRegion,
) {
  return analyzeRegion(pixels, gray, width, height, region);
}

function isExtremeExposure(region: PassportRegionQuality): boolean {
  return (
    region.meanLuminance < PASSPORT_FINAL_THRESHOLDS.extremeDarkMean
    && region.darkPixelRatio > PASSPORT_FINAL_THRESHOLDS.extremeDarkRatio
  ) || (
    region.meanLuminance > PASSPORT_FINAL_THRESHOLDS.extremeBrightMean
    && region.clippedHighlightRatio
      > PASSPORT_FINAL_THRESHOLDS.extremeBrightRatio
  );
}

function isSeverelyUnreadable(region: PassportRegionQuality): boolean {
  return (
    region.sharpness < PASSPORT_FINAL_THRESHOLDS.severeSharpness
    && region.detailDensity
      < PASSPORT_FINAL_THRESHOLDS.severeDetailDensity
  ) || (
    region.contrast < PASSPORT_FINAL_THRESHOLDS.severeTextContrast
    && region.detailDensity
      < PASSPORT_FINAL_THRESHOLDS.severeDetailDensity
  );
}

function isSoft(region: PassportRegionQuality): boolean {
  return region.sharpness < PASSPORT_FINAL_THRESHOLDS.softSharpness
    || region.detailDensity
      < PASSPORT_FINAL_THRESHOLDS.softDetailDensity;
}

function isRegionEffectivelyBlank(
  region: PassportRegionQuality,
): boolean {
  return region.detailDensity < 0.008
    && region.contrast < 8;
}

function result(
  outcome: CameraValidationOutcome,
  reason: PassportFinalQualityReason,
  message: string,
  metrics: PassportFinalQualityMetrics,
  confirmationPrompt: string | null = null,
): PassportFinalQualityResult {
  return {
    outcome,
    reason,
    message,
    confirmationPrompt: outcome === "borderline"
      ? confirmationPrompt
      : null,
    metrics,
  };
}

function borderlineMessage(
  reason: PassportFinalQualityReason,
  pageSide: PassportPageSide,
): string {
  switch (reason) {
    case "slightly_soft":
      return "One part of this passport image is slightly soft. Check the preview carefully before continuing.";
    case "small_reflection":
      return "A small reflection is visible. Continue only if every important detail remains readable.";
    case "lower_resolution":
      return "This image has a lower-than-preferred resolution. Continue only if the printed details remain clear.";
    case "weak_screen_suspicion":
      return "This image has a weak screen-like signal, but no definite phone interface was found. Confirm that it is a direct photo of the physical passport.";
    case "document_area_missing":
      return `The passport ${pageSide} page is close to the edge of the image. Confirm that no important details are cut off.`;
    default:
      return "Check the captured passport carefully before continuing.";
  }
}

function invalidResult(
  sourceWidth: number,
  sourceHeight: number,
): PassportFinalQualityResult {
  const emptyRegion: PassportRegionQuality = {
    sharpness: 0,
    detailDensity: 0,
    contrast: 0,
    meanLuminance: 0,
    darkPixelRatio: 1,
    clippedHighlightRatio: 0,
  };
  return result(
    "hard_failure",
    "invalid_image",
    "The captured passport image could not be checked. Retake it before continuing.",
    {
      overall: emptyRegion,
      mainDetails: emptyRegion,
      lowerTextBand: emptyRegion,
      portrait: emptyRegion,
      effectiveCoverage: 0,
      strongBoundaryCount: 0,
      missingBoundaryLikely: false,
      obviousScreenSignals: 0,
      weakScreenSignals: 0,
      sourceWidth,
      sourceHeight,
    },
  );
}

function pixelBounds(
  region: NormalizedRegion,
  width: number,
  height: number,
) {
  return {
    left: Math.max(1, Math.round(region.left * (width - 1))),
    top: Math.max(1, Math.round(region.top * (height - 1))),
    right: Math.min(
      width - 2,
      Math.round(region.right * (width - 1)),
    ),
    bottom: Math.min(
      height - 2,
      Math.round(region.bottom * (height - 1)),
    ),
  };
}

function toGrayscale(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
): Uint8Array {
  const gray = new Uint8Array(width * height);
  for (
    let pixel = 0, offset = 0;
    pixel < gray.length;
    pixel += 1, offset += 4
  ) {
    gray[pixel] = Math.round(
      pixels[offset] * 0.299
      + pixels[offset + 1] * 0.587
      + pixels[offset + 2] * 0.114,
    );
  }
  return gray;
}

async function decodeImageFile(file: File): Promise<{
  image: CanvasImageSource;
  width: number;
  height: number;
  close: () => void;
}> {
  if (typeof createImageBitmap === "function") {
    const bitmap = await createImageBitmap(file);
    return {
      image: bitmap,
      width: bitmap.width,
      height: bitmap.height,
      close: () => bitmap.close(),
    };
  }

  const objectUrl = URL.createObjectURL(file);
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const element = new window.Image();
      element.onload = () => resolve(element);
      element.onerror = () => reject(
        new Error("The captured passport image could not be decoded."),
      );
      element.src = objectUrl;
    });
    return {
      image,
      width: image.naturalWidth,
      height: image.naturalHeight,
      close: () => URL.revokeObjectURL(objectUrl),
    };
  } catch (error) {
    URL.revokeObjectURL(objectUrl);
    throw error;
  }
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}

function roundMetric(value: number): number {
  return Math.round(value * 1000) / 1000;
}

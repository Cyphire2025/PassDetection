export type PassportPageSide = "front" | "back";

export type PassportFrameStatus =
  | "checking"
  | "no_document"
  | "incomplete_document"
  | "too_small"
  | "sideways"
  | "upside_down"
  | "excessive_skew"
  | "multiple_documents"
  | "screen_or_book"
  | "missing_mrz"
  | "not_passport_page"
  | "ready";

export interface NormalizedDocumentPoint {
  x: number;
  y: number;
}

export interface PassportDocumentQuad {
  topLeft: NormalizedDocumentPoint;
  topRight: NormalizedDocumentPoint;
  bottomRight: NormalizedDocumentPoint;
  bottomLeft: NormalizedDocumentPoint;
}

export interface PassportContentAnalysis {
  mrzScore: number;
  portraitScore: number;
  textBlockScore: number;
  layoutScore: number;
  criticalZoneObstructionScore: number;
  meanLuminance: number;
  textureRatio: number;
  screenLike: boolean;
  internalSeparator: boolean;
  upsideDownLikelihood: number;
}

export interface FrameDetectionResult extends PassportContentAnalysis {
  isDetected: boolean;
  confidence: number;
  visibleEdges: number;
  status: PassportFrameStatus;
  documentAreaRatio: number;
  aspectRatio: number;
  skewDegrees: number;
  quad: PassportDocumentQuad | null;
}

interface Point {
  x: number;
  y: number;
}

interface PixelQuad {
  topLeft: Point;
  topRight: Point;
  bottomRight: Point;
  bottomLeft: Point;
}

interface WeightedPoint extends Point {
  weight: number;
}

interface BoundaryLine {
  slope: number;
  intercept: number;
  support: number;
  strength: number;
}

interface QuadDetection {
  quad: PixelQuad | null;
  visibleEdges: number;
  minimumSupport: number;
}

interface QuadMetrics {
  areaRatio: number;
  aspectRatio: number;
  skewDegrees: number;
  oppositeSideRatio: number;
  touchesFrame: boolean;
}

interface TextBand {
  start: number;
  end: number;
  density: number;
  coverage: number;
}

interface Region {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

interface VideoCrop {
  left: number;
  top: number;
  width: number;
  height: number;
}

const SAMPLE_WIDTH = 320;
const SAMPLE_HEIGHT = 225;
const CANONICAL_WIDTH = 180;
const CANONICAL_HEIGHT = 126;
const BOUNDARY_EDGE_THRESHOLD = 28;
const MIN_BOUNDARY_SUPPORT = 0.34;
export const PASSPORT_CRITICAL_ZONE_OBSTRUCTION_THRESHOLD = 0.62;

const EMPTY_CONTENT_ANALYSIS: PassportContentAnalysis = {
  mrzScore: 0,
  portraitScore: 0,
  textBlockScore: 0,
  layoutScore: 0,
  criticalZoneObstructionScore: 0,
  meanLuminance: 0,
  textureRatio: 0,
  screenLike: false,
  internalSeparator: false,
  upsideDownLikelihood: 0,
};

/**
 * Browser adapter. The expensive logic remains in analyzePassportFramePixels,
 * which is deterministic and can move to a worker without changing decisions.
 */
export function detectPassportFrame(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement,
  pageSide: PassportPageSide = "front",
  guide: HTMLElement | null = null,
): FrameDetectionResult {
  if (!drawPassportGuideFrame(
    video,
    canvas,
    guide,
    SAMPLE_WIDTH,
    SAMPLE_HEIGHT,
  )) {
    return emptyFrameResult("checking");
  }

  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return emptyFrameResult("checking");
  const { data } = context.getImageData(0, 0, SAMPLE_WIDTH, SAMPLE_HEIGHT);
  return analyzePassportFramePixels(data, SAMPLE_WIDTH, SAMPLE_HEIGHT, pageSide);
}

/**
 * Copies the portion of the source camera that is actually visible in the
 * on-screen guide. The video is rendered with object-cover, so raw camera
 * coordinates differ substantially on portrait phones.
 */
export function drawPassportGuideFrame(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement,
  guide: HTMLElement | null,
  destinationWidth: number,
  destinationHeight: number,
): boolean {
  if (
    video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA
    || !video.videoWidth
    || !video.videoHeight
    || destinationWidth < 1
    || destinationHeight < 1
  ) {
    return false;
  }

  const crop = getGuideVideoCrop(video, guide);
  canvas.width = destinationWidth;
  canvas.height = destinationHeight;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return false;
  context.drawImage(
    video,
    crop.left,
    crop.top,
    crop.width,
    crop.height,
    0,
    0,
    destinationWidth,
    destinationHeight,
  );
  return true;
}

/**
 * Detects a complete document quadrilateral and then evaluates passport-page
 * layout inside that quadrilateral. A rectangle alone can never pass.
 */
export function analyzePassportFramePixels(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
  pageSide: PassportPageSide = "front",
): FrameDetectionResult {
  if (
    width < 80
    || height < 60
    || pixels.length < width * height * 4
  ) {
    return emptyFrameResult("checking");
  }

  const gray = toGrayscale(pixels, width, height);
  const quadDetection = detectDocumentQuad(gray, width, height);
  if (!quadDetection.quad) {
    return {
      ...emptyFrameResult(
        quadDetection.visibleEdges > 0
          ? "incomplete_document"
          : "no_document",
      ),
      visibleEdges: quadDetection.visibleEdges,
    };
  }

  const quadMetrics = measureQuad(quadDetection.quad, width, height);
  const normalizedQuad = normalizeQuad(quadDetection.quad, width, height);
  const geometryConfidence = clamp01(
    (quadDetection.minimumSupport / 0.72) * 0.44
    + Math.min(1, quadMetrics.areaRatio / 0.46) * 0.34
    + clamp01(1 - Math.abs(quadMetrics.aspectRatio - 1.42) / 0.65) * 0.22,
  );
  const base = {
    visibleEdges: quadDetection.visibleEdges,
    documentAreaRatio: roundMetric(quadMetrics.areaRatio),
    aspectRatio: roundMetric(quadMetrics.aspectRatio),
    skewDegrees: roundMetric(quadMetrics.skewDegrees),
    quad: normalizedQuad,
  };

  if (quadDetection.visibleEdges < 4 || quadMetrics.touchesFrame) {
    return resultWithContent(base, EMPTY_CONTENT_ANALYSIS, {
      status: "incomplete_document",
      confidence: geometryConfidence * 0.4,
    });
  }
  if (quadMetrics.aspectRatio < 0.94) {
    return resultWithContent(base, EMPTY_CONTENT_ANALYSIS, {
      status: "sideways",
      confidence: geometryConfidence * 0.55,
    });
  }
  if (quadMetrics.areaRatio < 0.36) {
    return resultWithContent(base, EMPTY_CONTENT_ANALYSIS, {
      status: "too_small",
      confidence: geometryConfidence * 0.45,
    });
  }
  if (
    quadMetrics.aspectRatio > 1.86
    || quadMetrics.oppositeSideRatio < 0.58
    || quadMetrics.skewDegrees > 19
  ) {
    return resultWithContent(base, EMPTY_CONTENT_ANALYSIS, {
      status: quadMetrics.aspectRatio > 1.86
        ? "not_passport_page"
        : "excessive_skew",
      confidence: geometryConfidence * 0.55,
    });
  }

  const canonicalColor = rectifyQuadColorForAnalysis(
    pixels,
    width,
    height,
    quadDetection.quad,
    CANONICAL_WIDTH,
    CANONICAL_HEIGHT,
  );
  const canonical = toGrayscale(
    canonicalColor,
    CANONICAL_WIDTH,
    CANONICAL_HEIGHT,
  );
  const content = analyzeCanonicalPassportPage(
    canonical,
    CANONICAL_WIDTH,
    CANONICAL_HEIGHT,
    pageSide,
    detectCriticalZoneObstruction(
      canonicalColor,
      CANONICAL_WIDTH,
      CANONICAL_HEIGHT,
      pageSide,
    ),
  );
  const contentConfidence = pageSide === "front"
    ? content.layoutScore
    : clamp01(
        content.textBlockScore * 0.62
        + content.textureRatio / 0.14 * 0.28
        + (content.meanLuminance >= 72 && content.meanLuminance <= 232 ? 0.1 : 0),
      );
  const confidence = clamp01(
    geometryConfidence * 0.42
    + contentConfidence * 0.58,
  );

  let status: PassportFrameStatus = "ready";
  if (content.screenLike) {
    status = "screen_or_book";
  } else if (content.internalSeparator) {
    status = "multiple_documents";
  } else if (
    content.criticalZoneObstructionScore
      >= PASSPORT_CRITICAL_ZONE_OBSTRUCTION_THRESHOLD
  ) {
    // Keep the public status contract stable. The camera hook exposes the
    // obstruction score separately so the UI can give precise guidance while
    // existing low-cardinality telemetry continues to use not_passport_page.
    status = "not_passport_page";
  } else if (
    pageSide === "front"
    && content.upsideDownLikelihood >= 0.56
  ) {
    status = "upside_down";
  } else if (pageSide === "front" && content.mrzScore < 0.65) {
    status = "missing_mrz";
  } else if (
    pageSide === "front"
    && (
      content.portraitScore < 0.3
      || content.textBlockScore < 0.3
      || content.layoutScore < 0.58
    )
  ) {
    status = "not_passport_page";
  } else if (
    pageSide === "back"
    && (
      content.textBlockScore < 0.34
      || content.textureRatio < 0.025
      || content.meanLuminance < 66
      || content.meanLuminance > 238
    )
  ) {
    status = "not_passport_page";
  } else if (confidence < (pageSide === "front" ? 0.69 : 0.62)) {
    status = "not_passport_page";
  }

  return {
    ...content,
    ...base,
    isDetected: status === "ready",
    confidence: roundMetric(confidence),
    status,
  };
}

/**
 * Evaluates an already cropped or corrected page. Used by the perspective
 * corrector to ensure a transform preserves passport-like structure.
 */
export function analyzePassportContentPixels(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
  pageSide: PassportPageSide = "front",
): PassportContentAnalysis {
  if (
    width < 80
    || height < 50
    || pixels.length < width * height * 4
  ) {
    return EMPTY_CONTENT_ANALYSIS;
  }
  const canonicalColor = resizeRgba(
    pixels,
    width,
    height,
    CANONICAL_WIDTH,
    CANONICAL_HEIGHT,
  );
  const canonical = toGrayscale(
    canonicalColor,
    CANONICAL_WIDTH,
    CANONICAL_HEIGHT,
  );
  return analyzeCanonicalPassportPage(
    canonical,
    CANONICAL_WIDTH,
    CANONICAL_HEIGHT,
    pageSide,
    detectCriticalZoneObstruction(
      canonicalColor,
      CANONICAL_WIDTH,
      CANONICAL_HEIGHT,
      pageSide,
    ),
  );
}

export function isPassportCorrectionContentSafe(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
  pageSide: PassportPageSide = "front",
): boolean {
  if (
    width < 80
    || height < 50
    || pixels.length < width * height * 4
  ) {
    return false;
  }
  const aspectRatio = width / Math.max(1, height);
  if (aspectRatio < 1.08 || aspectRatio > 1.85) return false;

  let nonBlank = 0;
  let gradient = 0;
  for (let y = 1; y < height - 1; y += 2) {
    for (let x = 1; x < width - 1; x += 2) {
      const offset = (y * width + x) * 4;
      const luminance = rgbaLuminance(pixels, offset);
      const rightLuminance = rgbaLuminance(pixels, offset + 4);
      const belowLuminance = rgbaLuminance(
        pixels,
        offset + width * 4,
      );
      if (luminance > 18 && luminance < 246) nonBlank += 1;
      if (
        Math.abs(luminance - rightLuminance)
        + Math.abs(luminance - belowLuminance) > 24
      ) {
        gradient += 1;
      }
    }
  }
  const samples = Math.max(
    1,
    Math.floor((width - 2) / 2)
      * Math.floor((height - 2) / 2),
  );
  if (nonBlank / samples < 0.3 || gradient / samples < 0.025) {
    return false;
  }

  const content = analyzePassportContentPixels(
    pixels,
    width,
    height,
    pageSide,
  );
  if (content.screenLike || content.internalSeparator) return false;
  if (
    content.criticalZoneObstructionScore
      >= PASSPORT_CRITICAL_ZONE_OBSTRUCTION_THRESHOLD
  ) {
    return false;
  }
  return pageSide === "front"
    ? content.mrzScore >= 0.48
      && content.portraitScore >= 0.26
      && content.textBlockScore >= 0.27
      && content.layoutScore >= 0.54
      && content.upsideDownLikelihood < 0.5
    : content.textBlockScore >= 0.3
      && content.textureRatio >= 0.022
      && content.meanLuminance >= 62
      && content.meanLuminance <= 240;
}

function analyzeCanonicalPassportPage(
  gray: Uint8Array,
  width: number,
  height: number,
  pageSide: PassportPageSide,
  criticalZoneObstructionScore = 0,
): PassportContentAnalysis {
  const upright = evaluateLayout(gray, width, height, pageSide);
  const invertedGray = rotateGray180(gray, width, height);
  const inverted = evaluateLayout(invertedGray, width, height, pageSide);
  const border = analyzeOuterBorder(gray, width, height);
  const internalSeparator = detectInternalSeparator(gray, width, height);
  const upsideDownLikelihood = pageSide === "front"
    && upright.mrzScore >= 0.35
    && upright.mrzScore < 0.75
    && inverted.mrzScore >= 0.78
    && inverted.portraitScore >= 0.72
    && inverted.textBlockScore >= 0.5
    && inverted.layoutScore >= upright.layoutScore + 0.1
      ? clamp01(
          0.55
          + (inverted.layoutScore - upright.layoutScore)
          + (inverted.mrzScore - upright.mrzScore) * 0.35,
        )
      : 0;

  return {
    mrzScore: roundMetric(upright.mrzScore),
    portraitScore: roundMetric(upright.portraitScore),
    textBlockScore: roundMetric(upright.textBlockScore),
    layoutScore: roundMetric(upright.layoutScore),
    criticalZoneObstructionScore: roundMetric(
      criticalZoneObstructionScore,
    ),
    meanLuminance: roundMetric(upright.meanLuminance),
    textureRatio: roundMetric(upright.textureRatio),
    screenLike: border.screenLike,
    internalSeparator,
    upsideDownLikelihood: roundMetric(upsideDownLikelihood),
  };
}

function evaluateLayout(
  gray: Uint8Array,
  width: number,
  height: number,
  pageSide: PassportPageSide,
) {
  const overall = regionStats(gray, width, height, {
    left: 0.03,
    right: 0.97,
    top: 0.04,
    bottom: 0.96,
  });
  const leftPortrait = portraitRegionScore(gray, width, height, {
    left: 0.05,
    right: 0.36,
    top: 0.09,
    bottom: 0.67,
  });
  const rightPortrait = portraitRegionScore(gray, width, height, {
    left: 0.64,
    right: 0.95,
    top: 0.09,
    bottom: 0.67,
  });
  const leftText = textRegionScore(gray, width, height, {
    left: 0.05,
    right: 0.57,
    top: 0.08,
    bottom: pageSide === "front" ? 0.68 : 0.9,
  });
  const rightText = textRegionScore(gray, width, height, {
    left: 0.43,
    right: 0.95,
    top: 0.08,
    bottom: pageSide === "front" ? 0.68 : 0.9,
  });
  const portraitOnLeft = leftPortrait * 0.46 + rightText * 0.54;
  const portraitOnRight = rightPortrait * 0.46 + leftText * 0.54;
  const portraitScore = portraitOnLeft >= portraitOnRight
    ? leftPortrait
    : rightPortrait;
  const textBlockScore = portraitOnLeft >= portraitOnRight
    ? rightText
    : leftText;
  const mrzScore = pageSide === "front"
    ? mrzRegionScore(gray, width, height)
    : 0;
  const layoutScore = pageSide === "front"
    ? clamp01(
        mrzScore * 0.44
        + portraitScore * 0.27
        + textBlockScore * 0.24
        + Math.min(1, overall.edgeRatio / 0.13) * 0.05,
      )
    : clamp01(
        Math.max(leftText, rightText) * 0.7
        + Math.min(1, overall.edgeRatio / 0.12) * 0.3,
      );

  return {
    mrzScore,
    portraitScore,
    textBlockScore: pageSide === "front"
      ? textBlockScore
      : Math.max(leftText, rightText),
    layoutScore,
    meanLuminance: overall.mean,
    textureRatio: overall.edgeRatio,
  };
}

function mrzRegionScore(
  gray: Uint8Array,
  width: number,
  height: number,
): number {
  const bands = findTextBands(
    gray,
    width,
    height,
    { left: 0.035, right: 0.965, top: 0.69, bottom: 0.965 },
    { minimumDensity: 0.085, minimumCoverage: 0.52, maximumDensity: 0.94 },
  );
  const strongBands = bands.filter((band) => (
    band.end - band.start + 1 >= 2
    && band.end - band.start + 1 <= Math.round(height * 0.11)
    && band.coverage >= 0.58
    && band.density >= 0.1
  ));
  if (strongBands.length === 0) return 0;

  const bestBands = [...strongBands]
    .sort((first, second) => (
      (second.coverage + second.density)
      - (first.coverage + first.density)
    ))
    .slice(0, 3);
  const averageCoverage = average(bestBands.map((band) => band.coverage));
  const averageDensity = average(bestBands.map((band) => band.density));
  const lineCountScore = strongBands.length === 2
    ? 1
    : strongBands.length === 3
      ? 0.44
    : strongBands.length === 1
      ? 0.32
      : strongBands.length > 3
        ? 0.16
        : 0;
  const coverageScore = clamp01((averageCoverage - 0.46) / 0.42);
  const densityScore = clamp01((averageDensity - 0.075) / 0.25);
  return clamp01(
    lineCountScore * 0.56
    + coverageScore * 0.3
    + densityScore * 0.14,
  );
}

function textRegionScore(
  gray: Uint8Array,
  width: number,
  height: number,
  region: Region,
): number {
  const bands = findTextBands(
    gray,
    width,
    height,
    region,
    { minimumDensity: 0.045, minimumCoverage: 0.2, maximumDensity: 0.62 },
  );
  const usefulBands = bands.filter((band) => (
    band.end - band.start + 1 <= Math.round(height * 0.12)
    && band.coverage >= 0.22
  ));
  if (usefulBands.length === 0) return 0;
  const lineCountScore = Math.min(1, usefulBands.length / 4);
  const coverageScore = clamp01(
    (average(usefulBands.map((band) => band.coverage)) - 0.16) / 0.5,
  );
  return clamp01(lineCountScore * 0.68 + coverageScore * 0.32);
}

function portraitRegionScore(
  gray: Uint8Array,
  width: number,
  height: number,
  region: Region,
): number {
  const stats = regionStats(gray, width, height, region);
  const texturedCellRatio = texturedCells(gray, width, height, region);
  const rowTextureCoverage = texturedRowCoverage(
    gray,
    width,
    height,
    region,
  );
  const varianceScore = clamp01((stats.deviation - 17) / 35);
  const edgeScore = clamp01((stats.edgeRatio - 0.035) / 0.2);
  const cellsScore = clamp01((texturedCellRatio - 0.18) / 0.6);
  const continuityScore = clamp01((rowTextureCoverage - 0.25) / 0.5);
  const toneScore = clamp01((stats.darkRatio - 0.12) / 0.28)
    * clamp01((0.82 - stats.darkRatio) / 0.22);
  const isotropyScore = clamp01((stats.edgeIsotropy - 0.28) / 0.62);
  return clamp01(
    varianceScore * 0.1
    + edgeScore * 0.1
    + cellsScore * 0.1
    + continuityScore * 0.3
    + toneScore * 0.24
    + isotropyScore * 0.16,
  );
}

function findTextBands(
  gray: Uint8Array,
  width: number,
  height: number,
  region: Region,
  thresholds: {
    minimumDensity: number;
    minimumCoverage: number;
    maximumDensity: number;
  },
): TextBand[] {
  const bounds = pixelRegion(region, width, height);
  const binCount = 16;
  const rows: Array<{ active: boolean; density: number; coverage: number }> = [];
  for (let y = bounds.top; y <= bounds.bottom; y += 1) {
    const bins = new Uint16Array(binCount);
    let signals = 0;
    let samples = 0;
    for (let x = bounds.left + 1; x < bounds.right; x += 1) {
      const offset = y * width + x;
      const value = gray[offset];
      const isSignal = value <= 164;
      if (isSignal) {
        signals += 1;
        const bin = Math.min(
          binCount - 1,
          Math.floor(((x - bounds.left) / Math.max(1, bounds.right - bounds.left)) * binCount),
        );
        bins[bin] += 1;
      }
      samples += 1;
    }
    const density = signals / Math.max(1, samples);
    const minimumBinSignals = Math.max(
      1,
      Math.floor((bounds.right - bounds.left) / binCount * 0.08),
    );
    const coverage = bins.filter((count) => count >= minimumBinSignals).length / binCount;
    rows.push({
      active: density >= thresholds.minimumDensity
        && density <= thresholds.maximumDensity
        && coverage >= thresholds.minimumCoverage,
      density,
      coverage,
    });
  }

  const bands: TextBand[] = [];
  let start = -1;
  let lastActive = -1;
  let densityTotal = 0;
  let maximumCoverage = 0;
  let activeRows = 0;
  const closeBand = () => {
    if (start < 0 || lastActive < start) return;
    bands.push({
      start: bounds.top + start,
      end: bounds.top + lastActive,
      density: densityTotal / Math.max(1, activeRows),
      coverage: maximumCoverage,
    });
    start = -1;
    lastActive = -1;
    densityTotal = 0;
    maximumCoverage = 0;
    activeRows = 0;
  };

  for (let index = 0; index < rows.length; index += 1) {
    const row = rows[index];
    if (row.active) {
      if (start < 0) start = index;
      lastActive = index;
      densityTotal += row.density;
      maximumCoverage = Math.max(maximumCoverage, row.coverage);
      activeRows += 1;
    } else if (start >= 0 && index - lastActive > 1) {
      closeBand();
    }
  }
  closeBand();
  return bands;
}

function detectDocumentQuad(
  gray: Uint8Array,
  width: number,
  height: number,
): QuadDetection {
  const left = fitVerticalBoundary(gray, width, height, "left");
  const right = fitVerticalBoundary(gray, width, height, "right");
  const top = fitHorizontalBoundary(gray, width, height, "top");
  const bottom = fitHorizontalBoundary(gray, width, height, "bottom");
  const lines = [left, right, top, bottom];
  const visibleEdges = lines.filter((line) => (
    line !== null && line.support >= MIN_BOUNDARY_SUPPORT
  )).length;
  if (!left || !right || !top || !bottom) {
    return { quad: null, visibleEdges, minimumSupport: 0 };
  }
  const minimumSupport = Math.min(
    left.support,
    right.support,
    top.support,
    bottom.support,
  );
  if (minimumSupport < MIN_BOUNDARY_SUPPORT) {
    return { quad: null, visibleEdges, minimumSupport };
  }

  const quad: PixelQuad = {
    topLeft: intersectVerticalAndHorizontal(left, top),
    topRight: intersectVerticalAndHorizontal(right, top),
    bottomRight: intersectVerticalAndHorizontal(right, bottom),
    bottomLeft: intersectVerticalAndHorizontal(left, bottom),
  };
  if (!isFiniteConvexQuad(quad)) {
    return { quad: null, visibleEdges, minimumSupport };
  }
  return { quad, visibleEdges, minimumSupport };
}

function fitVerticalBoundary(
  gray: Uint8Array,
  width: number,
  height: number,
  side: "left" | "right",
): BoundaryLine | null {
  const points: WeightedPoint[] = [];
  const minimum = side === "left"
    ? Math.max(2, Math.round(width * 0.035))
    : Math.round(width * 0.63);
  const maximum = side === "left"
    ? Math.round(width * 0.37)
    : width - Math.max(3, Math.round(width * 0.035));
  const firstY = Math.round(height * 0.05);
  const lastY = Math.round(height * 0.95);
  let possible = 0;

  for (let y = firstY; y <= lastY; y += 2) {
    let bestX = minimum;
    let bestScore = 0;
    for (let x = minimum; x <= maximum; x += 1) {
      const offset = y * width + x;
      if (offset - 2 < 0 || offset + 2 >= gray.length) continue;
      const score = Math.abs(gray[offset + 2] - gray[offset - 2]);
      if (score > bestScore) {
        bestScore = score;
        bestX = x;
      }
    }
    if (bestScore >= BOUNDARY_EDGE_THRESHOLD) {
      points.push({ x: bestX, y, weight: bestScore });
    }
    possible += 1;
  }
  return fitRobustBoundary(points, "y", "x", possible, Math.max(3, width * 0.016));
}

function fitHorizontalBoundary(
  gray: Uint8Array,
  width: number,
  height: number,
  side: "top" | "bottom",
): BoundaryLine | null {
  const points: WeightedPoint[] = [];
  const minimum = side === "top"
    ? Math.max(2, Math.round(height * 0.025))
    : Math.round(height * 0.58);
  const maximum = side === "top"
    ? Math.round(height * 0.42)
    : height - Math.max(3, Math.round(height * 0.025));
  const firstX = Math.round(width * 0.04);
  const lastX = Math.round(width * 0.96);
  let possible = 0;

  for (let x = firstX; x <= lastX; x += 2) {
    let bestY = minimum;
    let bestScore = 0;
    for (let y = minimum; y <= maximum; y += 1) {
      const offset = y * width + x;
      if (offset - width * 2 < 0 || offset + width * 2 >= gray.length) continue;
      const score = Math.abs(
        gray[offset + width * 2]
        - gray[offset - width * 2],
      );
      if (score > bestScore) {
        bestScore = score;
        bestY = y;
      }
    }
    if (bestScore >= BOUNDARY_EDGE_THRESHOLD) {
      points.push({ x, y: bestY, weight: bestScore });
    }
    possible += 1;
  }
  return fitRobustBoundary(points, "x", "y", possible, Math.max(3, height * 0.018));
}

function fitRobustBoundary(
  points: WeightedPoint[],
  independent: "x" | "y",
  dependent: "x" | "y",
  possible: number,
  maximumResidual: number,
): BoundaryLine | null {
  if (points.length < Math.max(16, possible * 0.25)) return null;
  const initial = weightedLineFit(points, independent, dependent);
  if (!initial) return null;
  const inliers = points.filter((point) => (
    Math.abs(
      point[dependent]
      - (initial.slope * point[independent] + initial.intercept),
    ) <= maximumResidual
  ));
  if (inliers.length < Math.max(14, possible * 0.28)) return null;
  const refined = weightedLineFit(inliers, independent, dependent);
  if (!refined) return null;
  return {
    ...refined,
    support: inliers.length / Math.max(1, possible),
    strength: average(inliers.map((point) => point.weight)),
  };
}

function weightedLineFit(
  points: WeightedPoint[],
  independent: "x" | "y",
  dependent: "x" | "y",
): Pick<BoundaryLine, "slope" | "intercept"> | null {
  let totalWeight = 0;
  let independentMean = 0;
  let dependentMean = 0;
  for (const point of points) {
    totalWeight += point.weight;
    independentMean += point[independent] * point.weight;
    dependentMean += point[dependent] * point.weight;
  }
  if (totalWeight <= 0) return null;
  independentMean /= totalWeight;
  dependentMean /= totalWeight;

  let numerator = 0;
  let denominator = 0;
  for (const point of points) {
    const delta = point[independent] - independentMean;
    numerator += point.weight * delta * (point[dependent] - dependentMean);
    denominator += point.weight * delta * delta;
  }
  if (denominator < 0.001) return null;
  const slope = numerator / denominator;
  return {
    slope,
    intercept: dependentMean - slope * independentMean,
  };
}

function intersectVerticalAndHorizontal(
  vertical: BoundaryLine,
  horizontal: BoundaryLine,
): Point {
  const denominator = 1 - vertical.slope * horizontal.slope;
  const x = Math.abs(denominator) < 0.0001
    ? vertical.intercept
    : (
        vertical.slope * horizontal.intercept
        + vertical.intercept
      ) / denominator;
  return {
    x,
    y: horizontal.slope * x + horizontal.intercept,
  };
}

function measureQuad(
  quad: PixelQuad,
  width: number,
  height: number,
): QuadMetrics {
  const topWidth = distance(quad.topLeft, quad.topRight);
  const bottomWidth = distance(quad.bottomLeft, quad.bottomRight);
  const leftHeight = distance(quad.topLeft, quad.bottomLeft);
  const rightHeight = distance(quad.topRight, quad.bottomRight);
  const averageWidth = (topWidth + bottomWidth) / 2;
  const averageHeight = (leftHeight + rightHeight) / 2;
  const topAngle = Math.atan2(
    quad.topRight.y - quad.topLeft.y,
    quad.topRight.x - quad.topLeft.x,
  );
  const bottomAngle = Math.atan2(
    quad.bottomRight.y - quad.bottomLeft.y,
    quad.bottomRight.x - quad.bottomLeft.x,
  );
  const points = [
    quad.topLeft,
    quad.topRight,
    quad.bottomRight,
    quad.bottomLeft,
  ];
  const edgeMargin = Math.max(3, Math.min(width, height) * 0.018);
  return {
    areaRatio: polygonArea(points) / Math.max(1, width * height),
    aspectRatio: averageWidth / Math.max(1, averageHeight),
    skewDegrees: Math.abs((topAngle + bottomAngle) / 2) * (180 / Math.PI),
    oppositeSideRatio: Math.min(
      topWidth / Math.max(1, bottomWidth),
      bottomWidth / Math.max(1, topWidth),
      leftHeight / Math.max(1, rightHeight),
      rightHeight / Math.max(1, leftHeight),
    ),
    touchesFrame: points.some((point) => (
      point.x <= edgeMargin
      || point.x >= width - edgeMargin
      || point.y <= edgeMargin
      || point.y >= height - edgeMargin
    )),
  };
}

function rectifyQuadColorForAnalysis(
  pixels: Uint8ClampedArray,
  sourceWidth: number,
  sourceHeight: number,
  quad: PixelQuad,
  destinationWidth: number,
  destinationHeight: number,
): Uint8ClampedArray {
  const output = new Uint8ClampedArray(
    destinationWidth * destinationHeight * 4,
  );
  for (let y = 0; y < destinationHeight; y += 1) {
    const v = y / Math.max(1, destinationHeight - 1);
    for (let x = 0; x < destinationWidth; x += 1) {
      const u = x / Math.max(1, destinationWidth - 1);
      const topX = quad.topLeft.x * (1 - u) + quad.topRight.x * u;
      const topY = quad.topLeft.y * (1 - u) + quad.topRight.y * u;
      const bottomX = quad.bottomLeft.x * (1 - u) + quad.bottomRight.x * u;
      const bottomY = quad.bottomLeft.y * (1 - u) + quad.bottomRight.y * u;
      const sourceX = topX * (1 - v) + bottomX * v;
      const sourceY = topY * (1 - v) + bottomY * v;
      const destinationOffset = (y * destinationWidth + x) * 4;
      for (let channel = 0; channel < 3; channel += 1) {
        output[destinationOffset + channel] = sampleRgbaChannel(
          pixels,
          sourceWidth,
          sourceHeight,
          sourceX,
          sourceY,
          channel,
        );
      }
      output[destinationOffset + 3] = 255;
    }
  }
  return output;
}

function resizeRgba(
  source: Uint8ClampedArray,
  sourceWidth: number,
  sourceHeight: number,
  destinationWidth: number,
  destinationHeight: number,
): Uint8ClampedArray {
  const output = new Uint8ClampedArray(
    destinationWidth * destinationHeight * 4,
  );
  for (let y = 0; y < destinationHeight; y += 1) {
    const sourceY = y / Math.max(1, destinationHeight - 1) * (sourceHeight - 1);
    for (let x = 0; x < destinationWidth; x += 1) {
      const sourceX = x / Math.max(1, destinationWidth - 1) * (sourceWidth - 1);
      const destinationOffset = (y * destinationWidth + x) * 4;
      for (let channel = 0; channel < 3; channel += 1) {
        output[destinationOffset + channel] = sampleRgbaChannel(
          source,
          sourceWidth,
          sourceHeight,
          sourceX,
          sourceY,
          channel,
        );
      }
      output[destinationOffset + 3] = 255;
    }
  }
  return output;
}

/**
 * This is deliberately not a general-purpose hand detector. It only rejects a
 * coherent skin-coloured region when it enters from a physical page edge,
 * reaches deeply into a printed-data zone, and is large enough to hide useful
 * content. Requiring all of those signals avoids treating the holder portrait
 * or a warm passport substrate as a finger.
 */
function detectCriticalZoneObstruction(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
  pageSide: PassportPageSide,
): number {
  if (
    width < 40
    || height < 30
    || pixels.length < width * height * 4
  ) {
    return 0;
  }

  const mask = new Uint8Array(width * height);
  for (let index = 0; index < mask.length; index += 1) {
    const offset = index * 4;
    if (isLikelySkinPixel(
      pixels[offset],
      pixels[offset + 1],
      pixels[offset + 2],
      pixels[offset + 3],
    )) {
      mask[index] = 1;
    }
  }

  const edgeBandX = Math.max(2, Math.round(width * 0.035));
  const edgeBandY = Math.max(2, Math.round(height * 0.035));
  const totalPixels = width * height;
  let maximumScore = 0;

  for (let start = 0; start < mask.length; start += 1) {
    if (!mask[start]) continue;
    const stack = [start];
    mask[start] = 0;
    let pixelCount = 0;
    let criticalPixels = 0;
    let minimumX = width;
    let maximumX = 0;
    let minimumY = height;
    let maximumY = 0;
    let touchesLeft = false;
    let touchesRight = false;
    let touchesTop = false;
    let touchesBottom = false;

    while (stack.length) {
      const current = stack.pop();
      if (current === undefined) break;
      const x = current % width;
      const y = Math.floor(current / width);
      pixelCount += 1;
      minimumX = Math.min(minimumX, x);
      maximumX = Math.max(maximumX, x);
      minimumY = Math.min(minimumY, y);
      maximumY = Math.max(maximumY, y);
      touchesLeft ||= x <= edgeBandX;
      touchesRight ||= x >= width - 1 - edgeBandX;
      touchesTop ||= y <= edgeBandY;
      touchesBottom ||= y >= height - 1 - edgeBandY;
      if (isCriticalPassportZone(x, y, width, height, pageSide)) {
        criticalPixels += 1;
      }

      for (let offsetY = -1; offsetY <= 1; offsetY += 1) {
        for (let offsetX = -1; offsetX <= 1; offsetX += 1) {
          if (offsetX === 0 && offsetY === 0) continue;
          const nextX = x + offsetX;
          const nextY = y + offsetY;
          if (
            nextX < 0
            || nextX >= width
            || nextY < 0
            || nextY >= height
          ) {
            continue;
          }
          const next = nextY * width + nextX;
          if (!mask[next]) continue;
          mask[next] = 0;
          stack.push(next);
        }
      }
    }

    if (!(touchesLeft || touchesRight || touchesTop || touchesBottom)) {
      continue;
    }
    const areaRatio = pixelCount / totalPixels;
    // A component covering most of the rectified page is the document
    // substrate, not a foreground finger. A hand this large already destroys
    // the MRZ/text/portrait structural gates.
    if (areaRatio < 0.0065 || areaRatio > 0.32) continue;

    const penetration = Math.max(
      touchesLeft ? maximumX / Math.max(1, width - 1) : 0,
      touchesRight ? 1 - minimumX / Math.max(1, width - 1) : 0,
      touchesTop ? maximumY / Math.max(1, height - 1) : 0,
      touchesBottom ? 1 - minimumY / Math.max(1, height - 1) : 0,
    );
    const criticalRatio = criticalPixels / Math.max(1, pixelCount);
    if (penetration < 0.075 || criticalRatio < 0.42) continue;

    const componentWidth = maximumX - minimumX + 1;
    const componentHeight = maximumY - minimumY + 1;
    const fillRatio = pixelCount
      / Math.max(1, componentWidth * componentHeight);
    const score = clamp01(
      clamp01((areaRatio - 0.006) / 0.025) * 0.34
      + clamp01((penetration - 0.055) / 0.16) * 0.32
      + clamp01((fillRatio - 0.32) / 0.58) * 0.18
      + clamp01((criticalRatio - 0.35) / 0.5) * 0.16,
    );
    maximumScore = Math.max(maximumScore, score);
  }
  return maximumScore;
}

function isLikelySkinPixel(
  red: number,
  green: number,
  blue: number,
  alpha: number,
): boolean {
  if (
    alpha < 180
    || red < 42
    || green < 24
    || blue < 14
    || red <= green
    || green < blue * 0.88
    || red - green < 4
    || red - blue < 15
    || Math.max(red, green, blue) - Math.min(red, green, blue) < 16
  ) {
    return false;
  }
  const chromaBlue = (
    128
    - red * 0.168736
    - green * 0.331264
    + blue * 0.5
  );
  const chromaRed = (
    128
    + red * 0.5
    - green * 0.418688
    - blue * 0.081312
  );
  return chromaBlue >= 72
    && chromaBlue <= 132
    && chromaRed >= 134
    && chromaRed <= 181;
}

function isCriticalPassportZone(
  x: number,
  y: number,
  width: number,
  height: number,
  pageSide: PassportPageSide,
): boolean {
  const normalizedX = x / Math.max(1, width - 1);
  const normalizedY = y / Math.max(1, height - 1);
  if (normalizedX < 0.035 || normalizedX > 0.965) {
    return false;
  }
  if (pageSide === "back") {
    return normalizedY >= 0.07 && normalizedY <= 0.92;
  }
  return (
    normalizedY >= 0.08
    && normalizedY <= 0.67
  ) || (
    normalizedY >= 0.68
    && normalizedY <= 0.965
  );
}

function sampleRgbaChannel(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
  x: number,
  y: number,
  channel: number,
): number {
  const clampedX = Math.max(0, Math.min(width - 1, x));
  const clampedY = Math.max(0, Math.min(height - 1, y));
  const x0 = Math.floor(clampedX);
  const y0 = Math.floor(clampedY);
  const x1 = Math.min(width - 1, x0 + 1);
  const y1 = Math.min(height - 1, y0 + 1);
  const xWeight = clampedX - x0;
  const yWeight = clampedY - y0;
  const top = pixels[(y0 * width + x0) * 4 + channel] * (1 - xWeight)
    + pixels[(y0 * width + x1) * 4 + channel] * xWeight;
  const bottom = pixels[(y1 * width + x0) * 4 + channel] * (1 - xWeight)
    + pixels[(y1 * width + x1) * 4 + channel] * xWeight;
  return Math.round(top * (1 - yWeight) + bottom * yWeight);
}

function regionStats(
  gray: Uint8Array,
  width: number,
  height: number,
  region: Region,
) {
  const bounds = pixelRegion(region, width, height);
  let samples = 0;
  let total = 0;
  let squaredTotal = 0;
  let dark = 0;
  let edges = 0;
  let horizontalEdges = 0;
  let verticalEdges = 0;
  for (let y = bounds.top + 1; y < bounds.bottom; y += 1) {
    for (let x = bounds.left + 1; x < bounds.right; x += 1) {
      const offset = y * width + x;
      const value = gray[offset];
      const horizontalGradient = Math.abs(
        gray[offset + 1] - gray[offset - 1],
      );
      const verticalGradient = Math.abs(
        gray[offset + width] - gray[offset - width],
      );
      const gradient = horizontalGradient + verticalGradient;
      samples += 1;
      total += value;
      squaredTotal += value * value;
      if (value < 145) dark += 1;
      if (gradient >= 38) edges += 1;
      if (horizontalGradient >= 28) horizontalEdges += 1;
      if (verticalGradient >= 28) verticalEdges += 1;
    }
  }
  const mean = total / Math.max(1, samples);
  return {
    mean,
    deviation: Math.sqrt(
      Math.max(0, squaredTotal / Math.max(1, samples) - mean * mean),
    ),
    darkRatio: dark / Math.max(1, samples),
    edgeRatio: edges / Math.max(1, samples),
    edgeIsotropy: Math.min(horizontalEdges, verticalEdges)
      / Math.max(1, Math.max(horizontalEdges, verticalEdges)),
  };
}

function texturedCells(
  gray: Uint8Array,
  width: number,
  height: number,
  region: Region,
): number {
  const bounds = pixelRegion(region, width, height);
  const columns = 4;
  const rows = 4;
  let textured = 0;
  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      const stats = regionStats(gray, width, height, {
        left: (
          bounds.left
          + (bounds.right - bounds.left) * column / columns
        ) / width,
        right: (
          bounds.left
          + (bounds.right - bounds.left) * (column + 1) / columns
        ) / width,
        top: (
          bounds.top
          + (bounds.bottom - bounds.top) * row / rows
        ) / height,
        bottom: (
          bounds.top
          + (bounds.bottom - bounds.top) * (row + 1) / rows
        ) / height,
      });
      if (stats.deviation >= 18 && stats.edgeRatio >= 0.04) textured += 1;
    }
  }
  return textured / (columns * rows);
}

function texturedRowCoverage(
  gray: Uint8Array,
  width: number,
  height: number,
  region: Region,
): number {
  const bounds = pixelRegion(region, width, height);
  let texturedRows = 0;
  let rows = 0;
  for (let y = bounds.top + 1; y < bounds.bottom; y += 1) {
    let edges = 0;
    let dark = 0;
    let samples = 0;
    for (let x = bounds.left + 1; x < bounds.right; x += 1) {
      const offset = y * width + x;
      const gradient = Math.abs(gray[offset + 1] - gray[offset - 1]);
      if (gradient >= 34) edges += 1;
      if (gray[offset] < 150) dark += 1;
      samples += 1;
    }
    const edgeRatio = edges / Math.max(1, samples);
    const darkRatio = dark / Math.max(1, samples);
    if (
      edgeRatio >= 0.12
      && darkRatio >= 0.08
      && darkRatio <= 0.82
    ) {
      texturedRows += 1;
    }
    rows += 1;
  }
  return texturedRows / Math.max(1, rows);
}

function analyzeOuterBorder(
  gray: Uint8Array,
  width: number,
  height: number,
) {
  const bandX = Math.max(2, Math.round(width * 0.055));
  const bandY = Math.max(2, Math.round(height * 0.055));
  let outerSamples = 0;
  let outerDark = 0;
  let outerTotal = 0;
  let innerSamples = 0;
  let innerTotal = 0;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const value = gray[y * width + x];
      const isOuter = x < bandX
        || x >= width - bandX
        || y < bandY
        || y >= height - bandY;
      if (isOuter) {
        outerSamples += 1;
        outerTotal += value;
        if (value < 72) outerDark += 1;
      } else {
        innerSamples += 1;
        innerTotal += value;
      }
    }
  }
  const outerMean = outerTotal / Math.max(1, outerSamples);
  const innerMean = innerTotal / Math.max(1, innerSamples);
  const outerDarkRatio = outerDark / Math.max(1, outerSamples);
  return {
    screenLike: outerDarkRatio >= 0.52 && innerMean - outerMean >= 38,
  };
}

function detectInternalSeparator(
  gray: Uint8Array,
  width: number,
  height: number,
): boolean {
  let maximumVerticalRun = 0;
  for (
    let x = Math.round(width * 0.36);
    x <= Math.round(width * 0.64);
    x += 1
  ) {
    let currentRun = 0;
    let longestRun = 0;
    let samples = 0;
    for (let y = Math.round(height * 0.08); y < height * 0.92; y += 1) {
      const offset = y * width + x;
      const gradient = Math.abs(gray[offset + 1] - gray[offset - 1]);
      if (gray[offset] < 82 || gradient >= 56) {
        currentRun += 1;
        longestRun = Math.max(longestRun, currentRun);
      } else {
        currentRun = 0;
      }
      samples += 1;
    }
    maximumVerticalRun = Math.max(
      maximumVerticalRun,
      longestRun / Math.max(1, samples),
    );
  }

  let maximumHorizontalRun = 0;
  for (
    let y = Math.round(height * 0.34);
    y <= Math.round(height * 0.64);
    y += 1
  ) {
    let currentRun = 0;
    let longestRun = 0;
    let samples = 0;
    for (let x = Math.round(width * 0.05); x < width * 0.95; x += 1) {
      const offset = y * width + x;
      const gradient = Math.abs(
        gray[offset + width]
        - gray[offset - width],
      );
      if (gray[offset] < 72 || gradient >= 62) {
        currentRun += 1;
        longestRun = Math.max(longestRun, currentRun);
      } else {
        currentRun = 0;
      }
      samples += 1;
    }
    maximumHorizontalRun = Math.max(
      maximumHorizontalRun,
      longestRun / Math.max(1, samples),
    );
  }
  return maximumVerticalRun >= 0.52
    || maximumHorizontalRun >= 0.64;
}

function rotateGray180(
  gray: Uint8Array,
  width: number,
  height: number,
): Uint8Array {
  const rotated = new Uint8Array(gray.length);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      rotated[(height - 1 - y) * width + (width - 1 - x)] = gray[y * width + x];
    }
  }
  return rotated;
}

function pixelRegion(region: Region, width: number, height: number) {
  return {
    left: Math.max(0, Math.min(width - 2, Math.round(region.left * width))),
    right: Math.max(1, Math.min(width - 1, Math.round(region.right * width))),
    top: Math.max(0, Math.min(height - 2, Math.round(region.top * height))),
    bottom: Math.max(1, Math.min(height - 1, Math.round(region.bottom * height))),
  };
}

function getGuideVideoCrop(
  video: HTMLVideoElement,
  guide: HTMLElement | null,
): VideoCrop {
  const fallback: VideoCrop = {
    left: 0,
    top: 0,
    width: video.videoWidth,
    height: video.videoHeight,
  };
  if (!guide) return fallback;

  const videoRect = video.getBoundingClientRect();
  const guideRect = guide.getBoundingClientRect();
  if (
    videoRect.width <= 0
    || videoRect.height <= 0
    || guideRect.width <= 0
    || guideRect.height <= 0
  ) {
    return fallback;
  }

  const scale = Math.max(
    videoRect.width / video.videoWidth,
    videoRect.height / video.videoHeight,
  );
  if (!Number.isFinite(scale) || scale <= 0) return fallback;
  const renderedWidth = video.videoWidth * scale;
  const renderedHeight = video.videoHeight * scale;
  const offsetX = (renderedWidth - videoRect.width) / 2;
  const offsetY = (renderedHeight - videoRect.height) / 2;
  const guideCrop: VideoCrop = {
    left: (guideRect.left - videoRect.left + offsetX) / scale,
    top: (guideRect.top - videoRect.top + offsetY) / scale,
    width: guideRect.width / scale,
    height: guideRect.height / scale,
  };

  // Keep enough context for all four physical page boundaries to sit inside
  // the analysis bitmap instead of directly touching its edge.
  const horizontalMargin = guideCrop.width * 0.1;
  const verticalMargin = guideCrop.height * 0.1;
  return clampVideoCrop(
    {
      left: guideCrop.left - horizontalMargin,
      top: guideCrop.top - verticalMargin,
      width: guideCrop.width + horizontalMargin * 2,
      height: guideCrop.height + verticalMargin * 2,
    },
    video.videoWidth,
    video.videoHeight,
  );
}

function clampVideoCrop(
  crop: VideoCrop,
  maximumWidth: number,
  maximumHeight: number,
): VideoCrop {
  const left = Math.max(0, Math.min(maximumWidth - 1, crop.left));
  const top = Math.max(0, Math.min(maximumHeight - 1, crop.top));
  const right = Math.max(
    left + 1,
    Math.min(maximumWidth, crop.left + crop.width),
  );
  const bottom = Math.max(
    top + 1,
    Math.min(maximumHeight, crop.top + crop.height),
  );
  return {
    left,
    top,
    width: right - left,
    height: bottom - top,
  };
}

function toGrayscale(
  data: Uint8ClampedArray,
  width: number,
  height: number,
): Uint8Array {
  const gray = new Uint8Array(width * height);
  for (let pixel = 0, offset = 0; pixel < gray.length; pixel += 1, offset += 4) {
    gray[pixel] = Math.round(
      data[offset] * 0.299
      + data[offset + 1] * 0.587
      + data[offset + 2] * 0.114,
    );
  }
  return gray;
}

function rgbaLuminance(
  pixels: Uint8ClampedArray,
  offset: number,
): number {
  return pixels[offset] * 0.299
    + pixels[offset + 1] * 0.587
    + pixels[offset + 2] * 0.114;
}

function normalizeQuad(
  quad: PixelQuad,
  width: number,
  height: number,
): PassportDocumentQuad {
  const normalize = (point: Point): NormalizedDocumentPoint => ({
    x: roundMetric(point.x / width),
    y: roundMetric(point.y / height),
  });
  return {
    topLeft: normalize(quad.topLeft),
    topRight: normalize(quad.topRight),
    bottomRight: normalize(quad.bottomRight),
    bottomLeft: normalize(quad.bottomLeft),
  };
}

function isFiniteConvexQuad(quad: PixelQuad): boolean {
  const points = [
    quad.topLeft,
    quad.topRight,
    quad.bottomRight,
    quad.bottomLeft,
  ];
  if (!points.every((point) => Number.isFinite(point.x) && Number.isFinite(point.y))) {
    return false;
  }
  if (
    quad.topLeft.x >= quad.topRight.x
    || quad.bottomLeft.x >= quad.bottomRight.x
    || quad.topLeft.y >= quad.bottomLeft.y
    || quad.topRight.y >= quad.bottomRight.y
  ) {
    return false;
  }
  let sign = 0;
  for (let index = 0; index < points.length; index += 1) {
    const current = points[index];
    const next = points[(index + 1) % points.length];
    const after = points[(index + 2) % points.length];
    const cross = (
      (next.x - current.x) * (after.y - next.y)
      - (next.y - current.y) * (after.x - next.x)
    );
    if (Math.abs(cross) < 0.001) continue;
    const nextSign = Math.sign(cross);
    if (sign !== 0 && nextSign !== sign) return false;
    sign = nextSign;
  }
  return sign !== 0;
}

function polygonArea(points: Point[]): number {
  let area = 0;
  for (let index = 0; index < points.length; index += 1) {
    const next = points[(index + 1) % points.length];
    area += points[index].x * next.y - next.x * points[index].y;
  }
  return Math.abs(area) / 2;
}

function distance(first: Point, second: Point): number {
  return Math.hypot(second.x - first.x, second.y - first.y);
}

function average(values: number[]): number {
  return values.length
    ? values.reduce((sum, value) => sum + value, 0) / values.length
    : 0;
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

function roundMetric(value: number): number {
  return Number(value.toFixed(3));
}

function resultWithContent(
  base: Pick<
    FrameDetectionResult,
    "visibleEdges" | "documentAreaRatio" | "aspectRatio" | "skewDegrees" | "quad"
  >,
  content: PassportContentAnalysis,
  state: { status: PassportFrameStatus; confidence: number },
): FrameDetectionResult {
  return {
    ...content,
    ...base,
    isDetected: false,
    confidence: roundMetric(state.confidence),
    status: state.status,
  };
}

function emptyFrameResult(status: PassportFrameStatus): FrameDetectionResult {
  return {
    ...EMPTY_CONTENT_ANALYSIS,
    isDetected: false,
    confidence: 0,
    visibleEdges: 0,
    status,
    documentAreaRatio: 0,
    aspectRatio: 0,
    skewDegrees: 0,
    quad: null,
  };
}

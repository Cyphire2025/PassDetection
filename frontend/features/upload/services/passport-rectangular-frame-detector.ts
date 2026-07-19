export type RectangularPassportFrameStatus =
  | "checking"
  | "no_document"
  | "incomplete_document"
  | "excessive_skew"
  | "not_passport_page"
  | "ready";

export interface RectangularPassportFrameResult {
  isDetected: boolean;
  confidence: number;
  visibleEdges: number;
  strongEdges: number;
  documentAreaRatio: number;
  skewDegrees: number;
  detailTileRatio: number;
  detailRowCoverage: number;
  status: RectangularPassportFrameStatus;
  lightingStatus: "good" | "too_dark" | "too_bright";
  meanLuminance: number;
  darkPixelRatio: number;
  brightPixelRatio: number;
  motionSignature: Uint8Array;
}

interface VideoCrop {
  left: number;
  top: number;
  width: number;
  height: number;
}

interface Point {
  x: number;
  y: number;
}

interface BoundaryEvidence {
  slope: number;
  intercept: number;
  support: number;
  segmentCoverage: number;
  averageContrast: number;
  polarityConsistency: number;
  score: number;
  strength: "strong" | "plausible";
}

interface DocumentQuad {
  topLeft: Point;
  topRight: Point;
  bottomRight: Point;
  bottomLeft: Point;
}

const PASSPORT_LIVE_THRESHOLDS = {
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

const SAMPLE_WIDTH = PASSPORT_LIVE_THRESHOLDS.sampleWidth;
const SAMPLE_HEIGHT = PASSPORT_LIVE_THRESHOLDS.sampleHeight;
const GUIDE_CONTEXT_MARGIN_RATIO = (
  PASSPORT_LIVE_THRESHOLDS.guideContextMarginRatio
);
const GUIDE_EDGE_MIN_RATIO = (
  GUIDE_CONTEXT_MARGIN_RATIO / (1 + GUIDE_CONTEXT_MARGIN_RATIO * 2)
);
const GUIDE_EDGE_MAX_RATIO = 1 - GUIDE_EDGE_MIN_RATIO;

/**
 * Lightweight live-camera gate for a complete, near-level physical page.
 *
 * The detector deliberately does not inspect passport layout or MRZ content.
 * It instead requires three strong coherent boundaries plus a plausible fourth
 * boundary, and checks that their quadrilateral fills and aligns with the
 * visible guide. This keeps a weak open-book edge usable without allowing
 * unrelated texture, a partial page, or a rotated page to unlock capture.
 */
export function detectRectangularPassportFrame(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement,
  guide: HTMLElement | null = null,
): RectangularPassportFrameResult {
  if (!drawGuideFrame(
    video,
    canvas,
    guide,
    SAMPLE_WIDTH,
    SAMPLE_HEIGHT,
  )) {
    return emptyResult("checking");
  }

  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return emptyResult("checking");
  const { data } = context.getImageData(
    0,
    0,
    SAMPLE_WIDTH,
    SAMPLE_HEIGHT,
  );
  return analyzeRectangularPassportFramePixels(
    data,
    SAMPLE_WIDTH,
    SAMPLE_HEIGHT,
  );
}

/**
 * Copies the camera pixels visible around the DOM guide. The video uses
 * object-cover, so this conversion keeps edge checks aligned on portrait
 * phones instead of assuming raw camera and viewport coordinates match.
 */
function drawGuideFrame(
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
  const horizontalMargin = guideCrop.width * GUIDE_CONTEXT_MARGIN_RATIO;
  const verticalMargin = guideCrop.height * GUIDE_CONTEXT_MARGIN_RATIO;

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

/** Deterministic edge-only analysis used by the browser adapter and tests. */
export function analyzeRectangularPassportFramePixels(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
): RectangularPassportFrameResult {
  if (
    width < 40
    || height < 30
    || pixels.length < width * height * 4
  ) {
    return emptyResult("checking");
  }

  const gray = toGrayscale(pixels, width, height);
  const left = findVerticalBoundary(
    gray,
    width,
    height,
    "left",
  );
  const right = findVerticalBoundary(
    gray,
    width,
    height,
    "right",
  );
  const top = findHorizontalBoundary(
    gray,
    width,
    height,
    "top",
  );
  const bottom = findHorizontalBoundary(
    gray,
    width,
    height,
    "bottom",
  );
  const boundaries = [left, right, top, bottom];
  const visibleEdges = boundaries.filter(Boolean).length;
  const strongEdges = boundaries.filter(
    (boundary) => boundary?.strength === "strong",
  ).length;
  const quad = left && right && top && bottom
    ? createDocumentQuad(left, right, top, bottom)
    : null;
  const geometry = quad && left && right && top && bottom
    ? measureDocumentGeometry(
        quad,
        left,
        right,
        top,
        bottom,
        width,
        height,
      )
    : null;
  const detail = quad
    ? analyzeInteriorDetail(gray, width, height, quad)
    : { tileRatio: 0, rowCoverage: 0 };
  const hasCompleteBoundaryEvidence = visibleEdges === 4
    && strongEdges >= PASSPORT_LIVE_THRESHOLDS.minimumStrongEdges;
  const hasDistributedInteriorDetail = (
    detail.tileRatio
      >= PASSPORT_LIVE_THRESHOLDS.minimumDetailedTileRatio
    && detail.rowCoverage
      >= PASSPORT_LIVE_THRESHOLDS.minimumDetailedRowCoverage
  );
  const isDetected = hasCompleteBoundaryEvidence
    && Boolean(geometry?.isGuideAligned)
    && hasDistributedInteriorDetail;
  const boundaryConfidence = boundaries.reduce(
    (sum, boundary) => sum + (boundary?.score ?? 0),
    0,
  ) / 4;
  const confidence = isDetected
    ? Math.min(
        1,
        boundaryConfidence * 0.67
          + Math.min(1, detail.tileRatio / 0.5) * 0.13
          + 0.2,
      )
    : Math.min(0.82, boundaryConfidence * 0.68);
  const exposure = analyzeExposure(gray);
  const motionSignature = createMotionSignature(gray, width, height);
  const status: RectangularPassportFrameStatus = isDetected
    ? "ready"
    : hasCompleteBoundaryEvidence
      && geometry?.hasExcessiveSkew
      ? "excessive_skew"
      : hasCompleteBoundaryEvidence
        && geometry?.isGuideAligned
        && !hasDistributedInteriorDetail
        ? "not_passport_page"
      : visibleEdges >= 1
        ? "incomplete_document"
        : "no_document";

  return {
    isDetected,
    confidence: roundMetric(confidence),
    visibleEdges,
    strongEdges,
    documentAreaRatio: roundMetric(geometry?.areaRatio ?? 0),
    skewDegrees: roundMetric(geometry?.skewDegrees ?? 0),
    detailTileRatio: roundMetric(detail.tileRatio),
    detailRowCoverage: roundMetric(detail.rowCoverage),
    ...exposure,
    motionSignature,
    status,
  };
}

function createMotionSignature(
  gray: Uint8Array,
  width: number,
  height: number,
): Uint8Array {
  const columns = 12;
  const rows = 8;
  const signature = new Uint8Array(columns * rows);
  for (let row = 0; row < rows; row += 1) {
    const startY = Math.floor((row * height) / rows);
    const endY = Math.max(
      startY + 1,
      Math.floor(((row + 1) * height) / rows),
    );
    for (let column = 0; column < columns; column += 1) {
      const startX = Math.floor((column * width) / columns);
      const endX = Math.max(
        startX + 1,
        Math.floor(((column + 1) * width) / columns),
      );
      let total = 0;
      let samples = 0;
      for (let y = startY; y < endY; y += 2) {
        for (let x = startX; x < endX; x += 2) {
          total += gray[y * width + x];
          samples += 1;
        }
      }
      signature[row * columns + column] = Math.round(
        total / Math.max(1, samples),
      );
    }
  }
  return signature;
}

function analyzeExposure(gray: Uint8Array) {
  let luminanceTotal = 0;
  let darkPixels = 0;
  let brightPixels = 0;
  for (let index = 0; index < gray.length; index += 2) {
    const luminance = gray[index];
    luminanceTotal += luminance;
    if (
      luminance <= PASSPORT_LIVE_THRESHOLDS.extremeDarkLuminance
    ) {
      darkPixels += 1;
    }
    if (
      luminance >= PASSPORT_LIVE_THRESHOLDS.extremeBrightLuminance
    ) {
      brightPixels += 1;
    }
  }
  const samples = Math.max(1, Math.ceil(gray.length / 2));
  const meanLuminance = luminanceTotal / samples;
  const darkPixelRatio = darkPixels / samples;
  const brightPixelRatio = brightPixels / samples;
  const lightingStatus = (
    meanLuminance < PASSPORT_LIVE_THRESHOLDS.extremeDarkMean
    && darkPixelRatio > PASSPORT_LIVE_THRESHOLDS.extremePixelRatio
  )
    ? "too_dark"
    : (
        meanLuminance > PASSPORT_LIVE_THRESHOLDS.extremeBrightMean
        && brightPixelRatio > PASSPORT_LIVE_THRESHOLDS.extremePixelRatio
      )
      ? "too_bright"
      : "good";
  return {
    lightingStatus,
    meanLuminance: roundMetric(meanLuminance),
    darkPixelRatio: roundMetric(darkPixelRatio),
    brightPixelRatio: roundMetric(brightPixelRatio),
  } as const;
}

function findVerticalBoundary(
  gray: Uint8Array,
  width: number,
  height: number,
  side: "left" | "right",
): BoundaryEvidence | null {
  return findBoundary(
    gray,
    width,
    height,
    "vertical",
    side,
    side === "left" ? GUIDE_EDGE_MIN_RATIO : GUIDE_EDGE_MAX_RATIO,
  );
}

function findHorizontalBoundary(
  gray: Uint8Array,
  width: number,
  height: number,
  side: "top" | "bottom",
): BoundaryEvidence | null {
  return findBoundary(
    gray,
    width,
    height,
    "horizontal",
    side,
    side === "top" ? GUIDE_EDGE_MIN_RATIO : GUIDE_EDGE_MAX_RATIO,
  );
}

function findBoundary(
  gray: Uint8Array,
  width: number,
  height: number,
  orientation: "vertical" | "horizontal",
  side: "left" | "right" | "top" | "bottom",
  expectedPositionRatio: number,
): BoundaryEvidence | null {
  const dependentSize = orientation === "vertical" ? width : height;
  const independentSize = orientation === "vertical" ? height : width;
  const expectedPosition = expectedPositionRatio * (dependentSize - 1);
  const positionTolerance = Math.max(
    4,
    dependentSize
      * PASSPORT_LIVE_THRESHOLDS.edgePositionToleranceRatio,
  );
  const minimumIntercept = Math.max(
    7,
    Math.floor(expectedPosition - positionTolerance),
  );
  const maximumIntercept = Math.min(
    dependentSize - 8,
    Math.ceil(expectedPosition + positionTolerance),
  );
  const segmentSamples = new Uint16Array(8);
  const segmentSupported = new Uint16Array(8);
  let best: BoundaryEvidence | null = null;

  for (
    let slope = -PASSPORT_LIVE_THRESHOLDS.maximumSearchSlope;
    slope <= PASSPORT_LIVE_THRESHOLDS.maximumSearchSlope + 0.0001;
    slope += PASSPORT_LIVE_THRESHOLDS.searchSlopeStep
  ) {
    for (
      let intercept = minimumIntercept;
      intercept <= maximumIntercept;
      intercept += 2
    ) {
      const evidence = evaluateBoundaryCandidate(
        gray,
        width,
        height,
        orientation,
        side,
        slope,
        intercept,
        expectedPosition,
        positionTolerance,
        independentSize,
        segmentSamples,
        segmentSupported,
      );
      if (!best || evidence.score > best.score) best = evidence;
    }
  }

  if (!best) return null;
  // Candidate search stores the boundary position at the frame centre to make
  // guide alignment independent of slope. Geometry uses the standard line
  // equation, so fold the centre offset into the intercept before returning.
  const standardBoundary = {
    ...best,
    intercept: roundMetric(
      best.intercept - best.slope * ((independentSize - 1) / 2),
    ),
  };
  if (
    best.support >= PASSPORT_LIVE_THRESHOLDS.strongEdgeSupport
    && best.segmentCoverage
      >= PASSPORT_LIVE_THRESHOLDS.strongSegmentCoverage
    && best.polarityConsistency
      >= PASSPORT_LIVE_THRESHOLDS.strongPolarityConsistency
    && best.averageContrast
      >= PASSPORT_LIVE_THRESHOLDS.strongAverageContrast
  ) {
    return { ...standardBoundary, strength: "strong" };
  }
  if (
    best.support >= PASSPORT_LIVE_THRESHOLDS.plausibleEdgeSupport
    && best.segmentCoverage
      >= PASSPORT_LIVE_THRESHOLDS.plausibleSegmentCoverage
    && best.polarityConsistency
      >= PASSPORT_LIVE_THRESHOLDS.plausiblePolarityConsistency
    && best.averageContrast
      >= PASSPORT_LIVE_THRESHOLDS.plausibleAverageContrast
  ) {
    return { ...standardBoundary, strength: "plausible" };
  }
  return null;
}

function evaluateBoundaryCandidate(
  gray: Uint8Array,
  width: number,
  height: number,
  orientation: "vertical" | "horizontal",
  side: "left" | "right" | "top" | "bottom",
  slope: number,
  intercept: number,
  expectedPosition: number,
  positionTolerance: number,
  independentSize: number,
  segmentSamples: Uint16Array,
  segmentSupported: Uint16Array,
): BoundaryEvidence {
  const firstIndependent = Math.round(independentSize * 0.08);
  const lastIndependent = Math.round(independentSize * 0.92);
  segmentSamples.fill(0);
  segmentSupported.fill(0);
  const segmentCount = segmentSamples.length;
  let samples = 0;
  let supported = 0;
  let positive = 0;
  let negative = 0;
  let contrastTotal = 0;

  for (
    let independent = firstIndependent;
    independent <= lastIndependent;
    independent += 2
  ) {
    const centeredIndependent = independent - (independentSize - 1) / 2;
    const dependent = Math.round(
      intercept + slope * centeredIndependent,
    );
    const contrast = boundaryStepContrast(
      gray,
      width,
      height,
      orientation,
      side,
      dependent,
      independent,
    );
    const segment = Math.min(
      segmentCount - 1,
      Math.floor(
        ((independent - firstIndependent)
          / Math.max(1, lastIndependent - firstIndependent + 1))
          * segmentCount,
      ),
    );
    segmentSamples[segment] += 1;
    samples += 1;
    if (
      Math.abs(contrast)
        < PASSPORT_LIVE_THRESHOLDS.edgeStepContrast
    ) {
      continue;
    }
    supported += 1;
    contrastTotal += Math.abs(contrast);
    segmentSupported[segment] += 1;
    if (contrast >= 0) positive += 1;
    else negative += 1;
  }

  let coveredSegments = 0;
  for (let segment = 0; segment < segmentCount; segment += 1) {
    if (
      segmentSupported[segment]
        / Math.max(1, segmentSamples[segment]) >= 0.3
    ) {
      coveredSegments += 1;
    }
  }
  const support = supported / Math.max(1, samples);
  const segmentCoverage = coveredSegments / segmentCount;
  const averageContrast = contrastTotal / Math.max(1, supported);
  const polarityConsistency = Math.max(positive, negative)
    / Math.max(1, supported);
  const alignment = Math.max(
    0,
    1 - Math.abs(intercept - expectedPosition) / positionTolerance,
  );
  const score = (
    support * 0.48
    + segmentCoverage * 0.22
    + Math.min(1, averageContrast / 34) * 0.18
    + polarityConsistency * 0.08
    + alignment * 0.04
  );
  return {
    slope: roundMetric(slope),
    intercept,
    support: roundMetric(support),
    segmentCoverage: roundMetric(segmentCoverage),
    averageContrast: roundMetric(averageContrast),
    polarityConsistency: roundMetric(polarityConsistency),
    score: roundMetric(score),
    strength: "plausible",
  };
}

/**
 * Measures a broad luminance step across a candidate boundary. Thin text,
 * keyboard legends, and seams normally brighten and darken within this span,
 * while a physical page edge keeps one side consistently different.
 */
function boundaryStepContrast(
  gray: Uint8Array,
  width: number,
  height: number,
  orientation: "vertical" | "horizontal",
  side: "left" | "right" | "top" | "bottom",
  dependent: number,
  independent: number,
): number {
  const nearOffset = 3;
  const farOffset = 6;
  let negativeTotal = 0;
  let positiveTotal = 0;
  let samples = 0;

  for (let offset = nearOffset; offset <= farOffset; offset += 1) {
    if (orientation === "vertical") {
      if (
        dependent - offset < 0
        || dependent + offset >= width
        || independent < 0
        || independent >= height
      ) {
        continue;
      }
      negativeTotal += gray[independent * width + dependent - offset];
      positiveTotal += gray[independent * width + dependent + offset];
    } else {
      if (
        dependent - offset < 0
        || dependent + offset >= height
        || independent < 0
        || independent >= width
      ) {
        continue;
      }
      negativeTotal += gray[(dependent - offset) * width + independent];
      positiveTotal += gray[(dependent + offset) * width + independent];
    }
    samples += 1;
  }
  if (samples === 0) return 0;
  const directionalContrast = (
    positiveTotal - negativeTotal
  ) / samples;
  const positiveDirectionIsInside = side === "left" || side === "top";
  return positiveDirectionIsInside
    ? directionalContrast
    : -directionalContrast;
}

/**
 * Looks only for useful visual detail distributed through the page interior.
 * It does not recognize text, fields, faces, or MRZ structure. Requiring
 * several low-resolution tiles across more than one row prevents a blank
 * booklet page with a narrow strip of the real information page from passing.
 */
function analyzeInteriorDetail(
  gray: Uint8Array,
  width: number,
  height: number,
  quad: DocumentQuad,
) {
  const columns = PASSPORT_LIVE_THRESHOLDS.detailColumns;
  const rows = PASSPORT_LIVE_THRESHOLDS.detailRows;
  const detailedByRow = new Uint8Array(rows);
  let detailedTiles = 0;

  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      const tile = sampleInteriorTile(
        gray,
        width,
        height,
        quad,
        column,
        row,
        columns,
        rows,
      );
      if (
        tile.edgeRatio
          < PASSPORT_LIVE_THRESHOLDS.minimumDetailEdgeRatio
        || tile.deviation
          < PASSPORT_LIVE_THRESHOLDS.minimumDetailDeviation
      ) {
        continue;
      }
      detailedTiles += 1;
      detailedByRow[row] = 1;
    }
  }
  const detailedRows = detailedByRow.reduce(
    (sum, detailed) => sum + detailed,
    0,
  );
  return {
    tileRatio: detailedTiles / Math.max(1, columns * rows),
    rowCoverage: detailedRows / Math.max(1, rows),
  };
}

function sampleInteriorTile(
  gray: Uint8Array,
  width: number,
  height: number,
  quad: DocumentQuad,
  column: number,
  row: number,
  columns: number,
  rows: number,
) {
  // Stay well inside the fitted quadrilateral so page/background transitions
  // or an open-book crease cannot masquerade as distributed printed detail.
  const insetStart = 0.14;
  const insetSpan = 0.72;
  const samplesAcross = 18;
  const samplesDown = 14;
  let total = 0;
  let squaredTotal = 0;
  let edgeSamples = 0;
  let samples = 0;

  for (let sampleY = 0; sampleY < samplesDown; sampleY += 1) {
    const v = insetStart + insetSpan * (
      (row + (sampleY + 0.5) / samplesDown) / rows
    );
    for (let sampleX = 0; sampleX < samplesAcross; sampleX += 1) {
      const u = insetStart + insetSpan * (
        (column + (sampleX + 0.5) / samplesAcross) / columns
      );
      const point = pointInsideQuad(quad, u, v);
      const x = Math.max(1, Math.min(width - 2, Math.round(point.x)));
      const y = Math.max(1, Math.min(height - 2, Math.round(point.y)));
      const offset = y * width + x;
      const value = gray[offset];
      const gradient = (
        Math.abs(gray[offset + 1] - gray[offset - 1])
        + Math.abs(gray[offset + width] - gray[offset - width])
      );
      total += value;
      squaredTotal += value * value;
      if (gradient >= PASSPORT_LIVE_THRESHOLDS.detailGradient) {
        edgeSamples += 1;
      }
      samples += 1;
    }
  }
  const mean = total / Math.max(1, samples);
  return {
    edgeRatio: edgeSamples / Math.max(1, samples),
    deviation: Math.sqrt(
      Math.max(0, squaredTotal / Math.max(1, samples) - mean * mean),
    ),
  };
}

function pointInsideQuad(
  quad: DocumentQuad,
  u: number,
  v: number,
): Point {
  const top = {
    x: quad.topLeft.x * (1 - u) + quad.topRight.x * u,
    y: quad.topLeft.y * (1 - u) + quad.topRight.y * u,
  };
  const bottom = {
    x: quad.bottomLeft.x * (1 - u) + quad.bottomRight.x * u,
    y: quad.bottomLeft.y * (1 - u) + quad.bottomRight.y * u,
  };
  return {
    x: top.x * (1 - v) + bottom.x * v,
    y: top.y * (1 - v) + bottom.y * v,
  };
}

function createDocumentQuad(
  left: BoundaryEvidence,
  right: BoundaryEvidence,
  top: BoundaryEvidence,
  bottom: BoundaryEvidence,
): DocumentQuad {
  return {
    topLeft: intersectBoundaries(left, top),
    topRight: intersectBoundaries(right, top),
    bottomRight: intersectBoundaries(right, bottom),
    bottomLeft: intersectBoundaries(left, bottom),
  };
}

function intersectBoundaries(
  vertical: BoundaryEvidence,
  horizontal: BoundaryEvidence,
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

function measureDocumentGeometry(
  quad: DocumentQuad,
  left: BoundaryEvidence,
  right: BoundaryEvidence,
  top: BoundaryEvidence,
  bottom: BoundaryEvidence,
  width: number,
  height: number,
) {
  const points = [
    quad.topLeft,
    quad.topRight,
    quad.bottomRight,
    quad.bottomLeft,
  ];
  if (
    !points.every(
      (point) => Number.isFinite(point.x) && Number.isFinite(point.y),
    )
  ) {
    return {
      areaRatio: 0,
      skewDegrees: 0,
      hasExcessiveSkew: false,
      isGuideAligned: false,
    };
  }
  const topSpan = distance(quad.topLeft, quad.topRight);
  const bottomSpan = distance(quad.bottomLeft, quad.bottomRight);
  const leftSpan = distance(quad.topLeft, quad.bottomLeft);
  const rightSpan = distance(quad.topRight, quad.bottomRight);
  const horizontalSpanRatio = (
    (topSpan + bottomSpan) / 2
  ) / Math.max(1, width);
  const verticalSpanRatio = (
    (leftSpan + rightSpan) / 2
  ) / Math.max(1, height);
  const areaRatio = polygonArea(points) / Math.max(1, width * height);
  const centerX = points.reduce((sum, point) => sum + point.x, 0) / 4;
  const centerY = points.reduce((sum, point) => sum + point.y, 0) / 4;
  const leftAngle = radiansToDegrees(Math.atan(-left.slope));
  const rightAngle = radiansToDegrees(Math.atan(-right.slope));
  const topAngle = radiansToDegrees(Math.atan(top.slope));
  const bottomAngle = radiansToDegrees(Math.atan(bottom.slope));
  const verticalAngle = (leftAngle + rightAngle) / 2;
  const horizontalAngle = (topAngle + bottomAngle) / 2;
  const skewDegrees = Math.abs(
    (verticalAngle + horizontalAngle) / 2,
  );
  const oppositeVerticalDelta = Math.abs(leftAngle - rightAngle);
  const oppositeHorizontalDelta = Math.abs(topAngle - bottomAngle);
  const axisAngleDelta = Math.abs(verticalAngle - horizontalAngle);
  const hasExcessiveSkew = (
    skewDegrees > PASSPORT_LIVE_THRESHOLDS.maximumReadySkewDegrees
    || oppositeVerticalDelta
      > PASSPORT_LIVE_THRESHOLDS.maximumOppositeEdgeAngleDelta
    || oppositeHorizontalDelta
      > PASSPORT_LIVE_THRESHOLDS.maximumOppositeEdgeAngleDelta
    || axisAngleDelta
      > PASSPORT_LIVE_THRESHOLDS.maximumAxisAngleDelta
  );
  const spansFitGuide = (
    horizontalSpanRatio
      >= PASSPORT_LIVE_THRESHOLDS.minimumDocumentSpanRatio
    && horizontalSpanRatio
      <= PASSPORT_LIVE_THRESHOLDS.maximumDocumentSpanRatio
    && verticalSpanRatio
      >= PASSPORT_LIVE_THRESHOLDS.minimumDocumentSpanRatio
    && verticalSpanRatio
      <= PASSPORT_LIVE_THRESHOLDS.maximumDocumentSpanRatio
  );
  const centerFitsGuide = (
    Math.abs(centerX / width - 0.5)
      <= PASSPORT_LIVE_THRESHOLDS.maximumCenterOffsetRatio
    && Math.abs(centerY / height - 0.5)
      <= PASSPORT_LIVE_THRESHOLDS.maximumCenterOffsetRatio
  );
  const areaFitsGuide = (
    areaRatio >= PASSPORT_LIVE_THRESHOLDS.minimumDocumentAreaRatio
    && areaRatio <= PASSPORT_LIVE_THRESHOLDS.maximumDocumentAreaRatio
  );
  const oppositeSpansAgree = (
    Math.min(topSpan, bottomSpan) / Math.max(1, Math.max(topSpan, bottomSpan))
      >= 0.78
    && Math.min(leftSpan, rightSpan) / Math.max(1, Math.max(leftSpan, rightSpan))
      >= 0.78
  );

  return {
    areaRatio,
    skewDegrees,
    hasExcessiveSkew,
    isGuideAligned: (
      !hasExcessiveSkew
      && spansFitGuide
      && centerFitsGuide
      && areaFitsGuide
      && oppositeSpansAgree
      && isConvexQuad(quad)
    ),
  };
}

function isConvexQuad(quad: DocumentQuad): boolean {
  const points = [
    quad.topLeft,
    quad.topRight,
    quad.bottomRight,
    quad.bottomLeft,
  ];
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

function radiansToDegrees(radians: number): number {
  return radians * (180 / Math.PI);
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

function emptyResult(
  status: RectangularPassportFrameStatus,
): RectangularPassportFrameResult {
  return {
    isDetected: false,
    confidence: 0,
    visibleEdges: 0,
    strongEdges: 0,
    documentAreaRatio: 0,
    skewDegrees: 0,
    detailTileRatio: 0,
    detailRowCoverage: 0,
    status,
    lightingStatus: "good",
    meanLuminance: 0,
    darkPixelRatio: 0,
    brightPixelRatio: 0,
    motionSignature: new Uint8Array(0),
  };
}

function roundMetric(value: number): number {
  return Math.round(value * 1000) / 1000;
}

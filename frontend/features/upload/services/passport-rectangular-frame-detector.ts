export type RectangularPassportFrameStatus =
  | "checking"
  | "no_document"
  | "incomplete_document"
  | "ready";

export interface RectangularPassportFrameResult {
  isDetected: boolean;
  confidence: number;
  visibleEdges: number;
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

const PASSPORT_LIVE_THRESHOLDS = {
  sampleWidth: 320,
  sampleHeight: 200,
  guideContextMarginRatio: 0.1,
  edgeSearchRatio: 0.075,
  edgeGradient: 18,
  minimumEdgeSupport: 0.24,
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
const EDGE_SEARCH_RATIO = PASSPORT_LIVE_THRESHOLDS.edgeSearchRatio;
const EDGE_GRADIENT_THRESHOLD = PASSPORT_LIVE_THRESHOLDS.edgeGradient;
const MIN_EDGE_SUPPORT = PASSPORT_LIVE_THRESHOLDS.minimumEdgeSupport;

/**
 * Permissive live-camera gate that checks only whether a page-sized rectangle
 * is aligned with the visible guide. Passport-layout and MRZ analysis remain
 * available in the strict detector, but are intentionally not part of this
 * capture-unlock decision.
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
  const sideScores = [
    verticalEdgeSupport(gray, width, height, GUIDE_EDGE_MIN_RATIO),
    verticalEdgeSupport(gray, width, height, GUIDE_EDGE_MAX_RATIO),
    horizontalEdgeSupport(gray, width, height, GUIDE_EDGE_MIN_RATIO),
    horizontalEdgeSupport(gray, width, height, GUIDE_EDGE_MAX_RATIO),
  ];
  const visibleEdges = sideScores.filter(
    (score) => score >= MIN_EDGE_SUPPORT,
  ).length;
  const strongestThree = [...sideScores]
    .sort((first, second) => second - first)
    .slice(0, 3);
  const confidence = Math.min(
    1,
    strongestThree.reduce((sum, score) => sum + score, 0) / 2.1,
  );
  const isDetected = visibleEdges >= 3;
  const exposure = analyzeExposure(gray);
  const motionSignature = createMotionSignature(gray, width, height);

  return {
    isDetected,
    confidence: roundMetric(confidence),
    visibleEdges,
    ...exposure,
    motionSignature,
    status: isDetected
      ? "ready"
      : visibleEdges >= 1
        ? "incomplete_document"
        : "no_document",
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

function verticalEdgeSupport(
  gray: Uint8Array,
  width: number,
  height: number,
  centerRatio: number,
): number {
  const center = Math.round((width - 1) * centerRatio);
  const radius = Math.max(3, Math.round(width * EDGE_SEARCH_RATIO));
  const minimumX = Math.max(1, center - radius);
  const maximumX = Math.min(width - 2, center + radius);
  const minimumY = Math.max(1, Math.round(height * 0.08));
  const maximumY = Math.min(height - 2, Math.round(height * 0.92));
  let supportedRows = 0;
  let sampledRows = 0;

  for (let y = minimumY; y <= maximumY; y += 2) {
    let strongestGradient = 0;
    for (let x = minimumX; x <= maximumX; x += 1) {
      const offset = y * width + x;
      strongestGradient = Math.max(
        strongestGradient,
        Math.abs(gray[offset + 1] - gray[offset - 1]),
      );
    }
    if (strongestGradient >= EDGE_GRADIENT_THRESHOLD) supportedRows += 1;
    sampledRows += 1;
  }

  return supportedRows / Math.max(1, sampledRows);
}

function horizontalEdgeSupport(
  gray: Uint8Array,
  width: number,
  height: number,
  centerRatio: number,
): number {
  const center = Math.round((height - 1) * centerRatio);
  const radius = Math.max(3, Math.round(height * EDGE_SEARCH_RATIO));
  const minimumY = Math.max(1, center - radius);
  const maximumY = Math.min(height - 2, center + radius);
  const minimumX = Math.max(1, Math.round(width * 0.08));
  const maximumX = Math.min(width - 2, Math.round(width * 0.92));
  let supportedColumns = 0;
  let sampledColumns = 0;

  for (let x = minimumX; x <= maximumX; x += 2) {
    let strongestGradient = 0;
    for (let y = minimumY; y <= maximumY; y += 1) {
      const offset = y * width + x;
      strongestGradient = Math.max(
        strongestGradient,
        Math.abs(gray[offset + width] - gray[offset - width]),
      );
    }
    if (strongestGradient >= EDGE_GRADIENT_THRESHOLD) {
      supportedColumns += 1;
    }
    sampledColumns += 1;
  }

  return supportedColumns / Math.max(1, sampledColumns);
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

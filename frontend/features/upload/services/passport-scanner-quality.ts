export interface BlurDetectionResult {
  isSharp: boolean;
  score: number;
}

export interface GlareDetectionResult {
  hasGlare: boolean;
  highlightRatio: number;
  largestClusterRatio: number;
}

export type LightingStatus = "good" | "too_dark" | "too_bright";

export interface LightingDetectionResult {
  status: LightingStatus;
  isWellLit: boolean;
  meanLuminance: number;
  darkPixelRatio: number;
  brightPixelRatio: number;
  contrast: number;
}

const SHARPNESS_THRESHOLD = 115;
const HIGHLIGHT_LUMINANCE_THRESHOLD = 242;
const HIGHLIGHT_CLUSTER_THRESHOLD = 0.028;
const HIGHLIGHT_RATIO_THRESHOLD = 0.11;
const DARK_PIXEL_THRESHOLD = 52;
const BRIGHT_PIXEL_THRESHOLD = 228;

const GUIDE_REGION = {
  leftRatio: 0.14,
  rightRatio: 0.86,
  topRatio: 0.18,
  bottomRatio: 0.82,
} as const;

export function evaluatePassportBlurPixels(
  data: Uint8ClampedArray,
  width: number,
  height: number,
): BlurDetectionResult {
  if (!validPixels(data, width, height)) {
    return { isSharp: false, score: 0 };
  }
  const gray = new Float32Array(width * height);
  for (let pixel = 0, index = 0; pixel < gray.length; pixel += 1, index += 4) {
    gray[pixel] = data[index] * 0.299
      + data[index + 1] * 0.587
      + data[index + 2] * 0.114;
  }

  const { left, right, top, bottom } = analysisBounds(width, height);
  let sum = 0;
  let squaredSum = 0;
  let samples = 0;
  for (let y = top + 1; y < bottom - 1; y += 1) {
    for (let x = left + 1; x < right - 1; x += 1) {
      const center = y * width + x;
      const laplacian = gray[center - 1] + gray[center + 1]
        + gray[center - width] + gray[center + width]
        - 4 * gray[center];
      sum += laplacian;
      squaredSum += laplacian * laplacian;
      samples += 1;
    }
  }
  if (!samples) return { isSharp: false, score: 0 };
  const mean = sum / samples;
  const variance = Math.max(0, squaredSum / samples - mean * mean);
  const score = Math.round(variance);
  return { isSharp: score >= SHARPNESS_THRESHOLD, score };
}

export function evaluatePassportGlarePixels(
  data: Uint8ClampedArray,
  width: number,
  height: number,
): GlareDetectionResult {
  if (!validPixels(data, width, height)) return emptyGlareResult();
  const bounds = analysisBounds(width, height);
  const roiWidth = Math.max(1, bounds.right - bounds.left);
  const roiHeight = Math.max(1, bounds.bottom - bounds.top);
  const totalPixels = roiWidth * roiHeight;
  const highlights = new Uint8Array(totalPixels);
  let highlightPixels = 0;
  let pointer = 0;

  for (let y = bounds.top; y < bounds.bottom; y += 1) {
    for (let x = bounds.left; x < bounds.right; x += 1) {
      const index = (y * width + x) * 4;
      const red = data[index];
      const green = data[index + 1];
      const blue = data[index + 2];
      const luminance = red * 0.299 + green * 0.587 + blue * 0.114;
      const channelSpread = Math.max(red, green, blue) - Math.min(red, green, blue);
      if (
        luminance >= HIGHLIGHT_LUMINANCE_THRESHOLD
        && channelSpread <= 26
      ) {
        highlights[pointer] = 1;
        highlightPixels += 1;
      }
      pointer += 1;
    }
  }

  const largestCluster = findLargestHighlightCluster(
    highlights,
    roiWidth,
    roiHeight,
  );
  const highlightRatio = highlightPixels / totalPixels;
  const largestClusterRatio = largestCluster / totalPixels;
  return {
    hasGlare: largestClusterRatio >= HIGHLIGHT_CLUSTER_THRESHOLD
      || highlightRatio >= HIGHLIGHT_RATIO_THRESHOLD,
    highlightRatio: Number(highlightRatio.toFixed(3)),
    largestClusterRatio: Number(largestClusterRatio.toFixed(3)),
  };
}

export function evaluatePassportLightingPixels(
  data: Uint8ClampedArray,
  width: number,
  height: number,
): LightingDetectionResult {
  if (!validPixels(data, width, height)) return emptyLightingResult();
  const bounds = analysisBounds(width, height);
  let sum = 0;
  let squaredSum = 0;
  let darkPixels = 0;
  let brightPixels = 0;
  let samples = 0;

  for (let y = bounds.top; y < bounds.bottom; y += 1) {
    for (let x = bounds.left; x < bounds.right; x += 1) {
      const index = (y * width + x) * 4;
      const luminance = data[index] * 0.299
        + data[index + 1] * 0.587
        + data[index + 2] * 0.114;
      sum += luminance;
      squaredSum += luminance * luminance;
      if (luminance <= DARK_PIXEL_THRESHOLD) darkPixels += 1;
      if (luminance >= BRIGHT_PIXEL_THRESHOLD) brightPixels += 1;
      samples += 1;
    }
  }
  if (!samples) return emptyLightingResult();

  const meanLuminance = sum / samples;
  const variance = Math.max(
    0,
    squaredSum / samples - meanLuminance * meanLuminance,
  );
  const contrast = Math.sqrt(variance);
  const darkPixelRatio = darkPixels / samples;
  const brightPixelRatio = brightPixels / samples;
  const status: LightingStatus = meanLuminance < 86
    || darkPixelRatio > 0.48
    || (meanLuminance < 106 && contrast < 32)
      ? "too_dark"
      : meanLuminance > 210 || brightPixelRatio > 0.28
        ? "too_bright"
        : "good";

  return {
    status,
    isWellLit: status === "good",
    meanLuminance: Math.round(meanLuminance),
    darkPixelRatio: Number(darkPixelRatio.toFixed(3)),
    brightPixelRatio: Number(brightPixelRatio.toFixed(3)),
    contrast: Math.round(contrast),
  };
}

function analysisBounds(width: number, height: number) {
  return {
    left: Math.round(width * GUIDE_REGION.leftRatio),
    right: Math.round(width * GUIDE_REGION.rightRatio),
    top: Math.round(height * GUIDE_REGION.topRatio),
    bottom: Math.round(height * GUIDE_REGION.bottomRatio),
  };
}

function validPixels(
  data: Uint8ClampedArray,
  width: number,
  height: number,
): boolean {
  return width >= 8
    && height >= 8
    && data.length >= width * height * 4;
}

function findLargestHighlightCluster(
  highlights: Uint8Array,
  width: number,
  height: number,
): number {
  const visited = new Uint8Array(highlights.length);
  let largestCluster = 0;
  for (let index = 0; index < highlights.length; index += 1) {
    if (!highlights[index] || visited[index]) continue;
    let clusterSize = 0;
    const queue = [index];
    visited[index] = 1;
    while (queue.length > 0) {
      const current = queue.pop();
      if (current === undefined) continue;
      clusterSize += 1;
      const x = current % width;
      const y = Math.floor(current / width);
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
          const nextIndex = nextY * width + nextX;
          if (!highlights[nextIndex] || visited[nextIndex]) continue;
          visited[nextIndex] = 1;
          queue.push(nextIndex);
        }
      }
    }
    largestCluster = Math.max(largestCluster, clusterSize);
  }
  return largestCluster;
}

function emptyGlareResult(): GlareDetectionResult {
  return {
    hasGlare: false,
    highlightRatio: 0,
    largestClusterRatio: 0,
  };
}

function emptyLightingResult(): LightingDetectionResult {
  return {
    status: "too_dark",
    isWellLit: false,
    meanLuminance: 0,
    darkPixelRatio: 0,
    brightPixelRatio: 0,
    contrast: 0,
  };
}

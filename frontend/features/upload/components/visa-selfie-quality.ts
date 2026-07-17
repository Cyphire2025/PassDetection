export interface WhiteBackgroundMetrics {
  isWhite: boolean;
  isLightNeutral: boolean;
  isPlain: boolean;
  failureReason: "not_light_neutral" | "not_plain" | null;
  averageLuminance: number;
  lightNeutralRatio: number;
  strongEdgeRatio: number;
  roughTextureRatio: number;
  luminanceDeviation: number;
  zoneMeanSpread: number;
}

const SAMPLE_STEP = 2;
// A photographed white wall can land well below paper-white (255) under normal
// home/office lighting. These limits intentionally judge "light and neutral",
// rather than requiring studio exposure.
const MIN_LIGHT_LUMINANCE = 132;
const MAX_NEUTRAL_CHROMA = 48;
const MIN_LIGHT_NEUTRAL_RATIO = 0.68;
const MIN_AVERAGE_LUMINANCE = 158;
const MIN_ZONE_LIGHT_NEUTRAL_RATIO = 0.52;
const MIN_ZONE_LUMINANCE = 128;
const MAX_ZONE_MEAN_SPREAD = 88;
const MAX_LUMINANCE_DEVIATION = 55;
const MAX_WITHIN_ZONE_DEVIATION = 21;
const MAX_STRONG_EDGE_RATIO = 0.08;
const MAX_ROUGH_TEXTURE_RATIO = 0.20;
const MAX_DIRECTIONAL_ROUGH_TEXTURE_RATIO = 0.14;
const MAX_DARK_PIXEL_RATIO = 0.16;
// The guide itself is 10% smaller, so retaining these guide-relative minima
// produces an approximately 10% smaller on-screen face requirement overall.
const MIN_FACE_WIDTH_RATIO = 0.31;
const MIN_FACE_HEIGHT_RATIO = 0.38;

/**
 * Evaluates conservative wall-only strips around the head and shoulders.
 *
 * A person's hair, ears, and clothing rarely follow the guide perfectly. Using
 * every pixel outside the ideal silhouette therefore produces false failures,
 * especially when the face is correctly close to the camera. The perimeter
 * mask below deliberately ignores the centre and lower edge where that spill
 * is most likely. The remaining wall samples are checked independently for:
 * lightness/neutrality, coverage in every quadrant, smooth lighting variation,
 * and high-frequency edges that indicate patterns or clutter.
 */
export function evaluateWhiteBackground(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
): WhiteBackgroundMetrics {
  if (width <= 0 || height <= 0 || pixels.length < width * height * 4) {
    return failedMetrics();
  }

  const gridWidth = Math.ceil(width / SAMPLE_STEP);
  const gridHeight = Math.ceil(height / SAMPLE_STEP);
  const sampledRed = new Float32Array(gridWidth * gridHeight);
  const sampledGreen = new Float32Array(gridWidth * gridHeight);
  const sampledBlue = new Float32Array(gridWidth * gridHeight);
  const sampledLuminance = new Float32Array(gridWidth * gridHeight);
  const sampledBackground = new Uint8Array(gridWidth * gridHeight);
  const zoneSamples = [0, 0, 0, 0];
  const zoneLightNeutralSamples = [0, 0, 0, 0];
  const zoneLuminance = [0, 0, 0, 0];
  let samples = 0;
  let lightNeutralSamples = 0;
  let darkSamples = 0;
  let luminanceTotal = 0;
  let luminanceSquaredTotal = 0;

  for (let y = 0, gridY = 0; y < height; y += SAMPLE_STEP, gridY += 1) {
    const normalizedY = (y + 0.5) / height;
    for (let x = 0, gridX = 0; x < width; x += SAMPLE_STEP, gridX += 1) {
      const normalizedX = (x + 0.5) / width;
      if (!isSafeWallSample(normalizedX, normalizedY)) continue;

      const pixelIndex = (y * width + x) * 4;
      const red = pixels[pixelIndex];
      const green = pixels[pixelIndex + 1];
      const blue = pixels[pixelIndex + 2];
      const luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue;
      const chroma = Math.max(red, green, blue) - Math.min(red, green, blue);
      const gridIndex = gridY * gridWidth + gridX;
      const zone = (normalizedY >= 0.5 ? 2 : 0) + (normalizedX >= 0.5 ? 1 : 0);

      sampledBackground[gridIndex] = 1;
      sampledRed[gridIndex] = red;
      sampledGreen[gridIndex] = green;
      sampledBlue[gridIndex] = blue;
      sampledLuminance[gridIndex] = luminance;
      samples += 1;
      luminanceTotal += luminance;
      luminanceSquaredTotal += luminance * luminance;
      zoneSamples[zone] += 1;
      zoneLuminance[zone] += luminance;
      if (luminance < 105) darkSamples += 1;

      // Permit a little more warm/cool cast as exposure rises, while rejecting
      // genuinely coloured walls at every brightness.
      const neutralChromaLimit = Math.min(MAX_NEUTRAL_CHROMA, 22 + luminance * 0.14);
      if (luminance >= MIN_LIGHT_LUMINANCE && chroma <= neutralChromaLimit) {
        lightNeutralSamples += 1;
        zoneLightNeutralSamples[zone] += 1;
      }
    }
  }

  if (samples === 0) return failedMetrics();

  let adjacentPairs = 0;
  let strongEdges = 0;
  let roughTexturePairs = 0;
  let horizontalPairs = 0;
  let horizontalRoughTexturePairs = 0;
  let verticalPairs = 0;
  let verticalRoughTexturePairs = 0;
  for (let gridY = 0; gridY < gridHeight; gridY += 1) {
    for (let gridX = 0; gridX < gridWidth; gridX += 1) {
      const gridIndex = gridY * gridWidth + gridX;
      if (!sampledBackground[gridIndex]) continue;
      if (gridX + 1 < gridWidth) {
        accumulatePair(gridIndex, gridIndex + 1, "horizontal");
      }
      if (gridY + 1 < gridHeight) {
        accumulatePair(gridIndex, gridIndex + gridWidth, "vertical");
      }
    }
  }

  function accumulatePair(first: number, second: number, direction: "horizontal" | "vertical") {
    if (!sampledBackground[second]) return;
    const luminanceDelta = Math.abs(sampledLuminance[first] - sampledLuminance[second]);
    const colorDelta = Math.max(
      Math.abs(sampledRed[first] - sampledRed[second]),
      Math.abs(sampledGreen[first] - sampledGreen[second]),
      Math.abs(sampledBlue[first] - sampledBlue[second]),
    );
    const isRough = luminanceDelta >= 15 || colorDelta >= 22;
    adjacentPairs += 1;
    if (luminanceDelta >= 32 || colorDelta >= 42) strongEdges += 1;
    if (isRough) roughTexturePairs += 1;
    if (direction === "horizontal") {
      horizontalPairs += 1;
      if (isRough) horizontalRoughTexturePairs += 1;
    } else {
      verticalPairs += 1;
      if (isRough) verticalRoughTexturePairs += 1;
    }
  }

  const averageLuminance = luminanceTotal / samples;
  const variance = Math.max(0, luminanceSquaredTotal / samples - averageLuminance ** 2);
  const luminanceDeviation = Math.sqrt(variance);
  const lightNeutralRatio = lightNeutralSamples / samples;
  const strongEdgeRatio = adjacentPairs > 0 ? strongEdges / adjacentPairs : 1;
  const roughTextureRatio = adjacentPairs > 0 ? roughTexturePairs / adjacentPairs : 1;
  const zoneMeans = zoneSamples.map((count, zone) => count > 0 ? zoneLuminance[zone] / count : 0);
  const zoneMeanSpread = Math.max(...zoneMeans) - Math.min(...zoneMeans);
  const horizontalRoughTextureRatio = horizontalPairs > 0
    ? horizontalRoughTexturePairs / horizontalPairs
    : 1;
  const verticalRoughTextureRatio = verticalPairs > 0
    ? verticalRoughTexturePairs / verticalPairs
    : 1;
  const directionalRoughTextureRatio = Math.max(
    horizontalRoughTextureRatio,
    verticalRoughTextureRatio,
  );
  let withinZoneSquaredTotal = 0;
  for (let gridY = 0; gridY < gridHeight; gridY += 1) {
    const normalizedY = (gridY * SAMPLE_STEP + 0.5) / height;
    for (let gridX = 0; gridX < gridWidth; gridX += 1) {
      const gridIndex = gridY * gridWidth + gridX;
      if (!sampledBackground[gridIndex]) continue;
      const normalizedX = (gridX * SAMPLE_STEP + 0.5) / width;
      const zone = (normalizedY >= 0.5 ? 2 : 0) + (normalizedX >= 0.5 ? 1 : 0);
      const delta = sampledLuminance[gridIndex] - zoneMeans[zone];
      withinZoneSquaredTotal += delta * delta;
    }
  }
  const withinZoneDeviation = Math.sqrt(withinZoneSquaredTotal / samples);
  const everyZoneIsLightNeutral = zoneSamples.every((count, zone) =>
    count > 0
    && zoneLightNeutralSamples[zone] / count >= MIN_ZONE_LIGHT_NEUTRAL_RATIO
    && zoneMeans[zone] >= MIN_ZONE_LUMINANCE,
  );
  const isLightNeutral = lightNeutralRatio >= MIN_LIGHT_NEUTRAL_RATIO
    && averageLuminance >= MIN_AVERAGE_LUMINANCE
    && everyZoneIsLightNeutral
    && zoneMeanSpread <= MAX_ZONE_MEAN_SPREAD
    && luminanceDeviation <= MAX_LUMINANCE_DEVIATION
    && darkSamples / samples <= MAX_DARK_PIXEL_RATIO;
  const isPlain = withinZoneDeviation <= MAX_WITHIN_ZONE_DEVIATION
    && strongEdgeRatio <= MAX_STRONG_EDGE_RATIO
    && roughTextureRatio <= MAX_ROUGH_TEXTURE_RATIO
    && directionalRoughTextureRatio <= MAX_DIRECTIONAL_ROUGH_TEXTURE_RATIO;
  const failureReason = !isPlain
    ? "not_plain"
    : !isLightNeutral
      ? "not_light_neutral"
      : null;

  return {
    isWhite: isLightNeutral && isPlain,
    isLightNeutral,
    isPlain,
    failureReason,
    averageLuminance,
    lightNeutralRatio,
    strongEdgeRatio,
    roughTextureRatio,
    luminanceDeviation,
    zoneMeanSpread,
  };
}

export function isVisaSelfieFaceLargeEnough(relativeWidth: number, relativeHeight: number): boolean {
  return relativeWidth >= MIN_FACE_WIDTH_RATIO && relativeHeight >= MIN_FACE_HEIGHT_RATIO;
}

export function isInsidePersonGuide(x: number, y: number): boolean {
  const head = ((x - 0.5) / 0.30) ** 2 + ((y - 0.34) / 0.32) ** 2 <= 1;
  if (head) return true;
  if (y < 0.58) return false;
  const progress = Math.min(1, (y - 0.58) / 0.42);
  const shoulderHalfWidth = 0.18 + progress * 0.30;
  return Math.abs(x - 0.5) <= shoulderHalfWidth;
}

/**
 * Samples only the parts of the guide crop that should remain wall even when a
 * correctly-sized person has untidy hair or broad shoulders. The narrowing
 * strips follow the natural widening of the person towards the bottom.
 */
function isSafeWallSample(x: number, y: number): boolean {
  // The lower portion is intentionally omitted: with the requested close crop,
  // shoulders and clothing legitimately reach both frame edges there.
  if (y >= 0.62) return false;
  if (y < 0.40) return x <= 0.06 || x >= 0.94;
  if (y < 0.58) return x <= 0.10 || x >= 0.90;
  return x <= 0.06 || x >= 0.94;
}

function failedMetrics(): WhiteBackgroundMetrics {
  return {
    isWhite: false,
    isLightNeutral: false,
    isPlain: false,
    failureReason: "not_light_neutral",
    averageLuminance: 0,
    lightNeutralRatio: 0,
    strongEdgeRatio: 1,
    roughTextureRatio: 1,
    luminanceDeviation: 0,
    zoneMeanSpread: 0,
  };
}

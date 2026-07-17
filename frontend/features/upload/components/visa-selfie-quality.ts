export interface WhiteBackgroundMetrics {
  isWhite: boolean;
  averageLuminance: number;
  lightNeutralRatio: number;
  strongEdgeRatio: number;
  roughTextureRatio: number;
  luminanceDeviation: number;
  zoneMeanSpread: number;
}

const SAMPLE_STEP = 2;
const MIN_LIGHT_LUMINANCE = 170;
const MAX_NEUTRAL_CHROMA = 32;
const MIN_LIGHT_NEUTRAL_RATIO = 0.62;
const MIN_AVERAGE_LUMINANCE = 180;
const MIN_ZONE_LIGHT_NEUTRAL_RATIO = 0.45;
const MIN_ZONE_LUMINANCE = 170;
const MAX_ZONE_MEAN_SPREAD = 60;
const MAX_LUMINANCE_DEVIATION = 45;
// The guide itself is 10% smaller, so retaining these guide-relative minima
// produces an approximately 10% smaller on-screen face requirement overall.
const MIN_FACE_WIDTH_RATIO = 0.31;
const MIN_FACE_HEIGHT_RATIO = 0.38;

/**
 * Evaluates only the area outside the expected head-and-shoulders silhouette.
 * The thresholds accept real white and off-white office walls under ordinary
 * indoor lighting while still rejecting dark, strongly colored, patterned,
 * or cluttered backgrounds.
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
  let luminanceTotal = 0;
  let luminanceSquaredTotal = 0;

  for (let y = 0, gridY = 0; y < height; y += SAMPLE_STEP, gridY += 1) {
    const normalizedY = (y + 0.5) / height;
    for (let x = 0, gridX = 0; x < width; x += SAMPLE_STEP, gridX += 1) {
      const normalizedX = (x + 0.5) / width;
      if (isInsidePersonGuide(normalizedX, normalizedY)) continue;

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
      if (luminance >= MIN_LIGHT_LUMINANCE && chroma <= MAX_NEUTRAL_CHROMA) {
        lightNeutralSamples += 1;
        zoneLightNeutralSamples[zone] += 1;
      }
    }
  }

  if (samples === 0) return failedMetrics();

  let adjacentPairs = 0;
  let strongEdges = 0;
  let roughTexturePairs = 0;
  for (let gridY = 0; gridY < gridHeight; gridY += 1) {
    for (let gridX = 0; gridX < gridWidth; gridX += 1) {
      const gridIndex = gridY * gridWidth + gridX;
      if (!sampledBackground[gridIndex]) continue;
      if (gridX + 1 < gridWidth) {
        accumulatePair(gridIndex, gridIndex + 1);
      }
      if (gridY + 1 < gridHeight) {
        accumulatePair(gridIndex, gridIndex + gridWidth);
      }
    }
  }

  function accumulatePair(first: number, second: number) {
    if (!sampledBackground[second]) return;
    const luminanceDelta = Math.abs(sampledLuminance[first] - sampledLuminance[second]);
    const colorDelta = Math.max(
      Math.abs(sampledRed[first] - sampledRed[second]),
      Math.abs(sampledGreen[first] - sampledGreen[second]),
      Math.abs(sampledBlue[first] - sampledBlue[second]),
    );
    adjacentPairs += 1;
    if (luminanceDelta >= 24 || colorDelta >= 32) strongEdges += 1;
    if (luminanceDelta >= 12 || colorDelta >= 18) roughTexturePairs += 1;
  }

  const averageLuminance = luminanceTotal / samples;
  const variance = Math.max(0, luminanceSquaredTotal / samples - averageLuminance ** 2);
  const luminanceDeviation = Math.sqrt(variance);
  const lightNeutralRatio = lightNeutralSamples / samples;
  const strongEdgeRatio = adjacentPairs > 0 ? strongEdges / adjacentPairs : 1;
  const roughTextureRatio = adjacentPairs > 0 ? roughTexturePairs / adjacentPairs : 1;
  const zoneMeans = zoneSamples.map((count, zone) => count > 0 ? zoneLuminance[zone] / count : 0);
  const zoneMeanSpread = Math.max(...zoneMeans) - Math.min(...zoneMeans);
  const everyZoneIsLightNeutral = zoneSamples.every((count, zone) =>
    count > 0
    && zoneLightNeutralSamples[zone] / count >= MIN_ZONE_LIGHT_NEUTRAL_RATIO
    && zoneMeans[zone] >= MIN_ZONE_LUMINANCE,
  );

  return {
    isWhite: lightNeutralRatio >= MIN_LIGHT_NEUTRAL_RATIO
      && averageLuminance >= MIN_AVERAGE_LUMINANCE
      && everyZoneIsLightNeutral
      && zoneMeanSpread <= MAX_ZONE_MEAN_SPREAD
      && luminanceDeviation <= MAX_LUMINANCE_DEVIATION
      && strongEdgeRatio <= 0.10
      && roughTextureRatio <= 0.34,
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

function failedMetrics(): WhiteBackgroundMetrics {
  return {
    isWhite: false,
    averageLuminance: 0,
    lightNeutralRatio: 0,
    strongEdgeRatio: 1,
    roughTextureRatio: 1,
    luminanceDeviation: 0,
    zoneMeanSpread: 0,
  };
}

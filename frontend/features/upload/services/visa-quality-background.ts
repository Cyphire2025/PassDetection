import type { WhiteBackgroundMetrics, VisaPhotoFaceGeometry } from "./visa-quality.types.ts";
import {
  SAMPLE_STEP, MIN_LIGHT_LUMINANCE, MAX_NEUTRAL_CHROMA, MIN_LIGHT_NEUTRAL_RATIO,
  MIN_AVERAGE_LUMINANCE, MIN_ZONE_LIGHT_NEUTRAL_RATIO, MIN_ZONE_LUMINANCE, MAX_ZONE_MEAN_SPREAD,
  MAX_LUMINANCE_DEVIATION, MAX_WITHIN_ZONE_DEVIATION, MAX_STRONG_EDGE_RATIO,
  MAX_ROUGH_TEXTURE_RATIO, MAX_DIRECTIONAL_ROUGH_TEXTURE_RATIO, MAX_DARK_PIXEL_RATIO,
  MAX_LINE_COVERAGE, MAX_REGIONAL_EDGE_RATIO, MAX_REGIONAL_DARK_RATIO, EXTREME_REGIONAL_EDGE_RATIO,
  EXTREME_REGIONAL_DARK_RATIO,
} from "./visa-quality-policy.ts";
import {
  isSafeWallSample, regionalIndex, maximumSupportedRatio, failedMetrics,
} from "./visa-quality-background-mask.ts";

/** Measures wall lightness, neutrality and structure outside the detected-person mask. */
export function evaluateWhiteBackground(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
  face?: VisaPhotoFaceGeometry,
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
  const regionalSamples = new Uint32Array(16);
  const regionalLightNeutralSamples = new Uint32Array(16);
  const regionalLuminance = new Float64Array(16);
  const regionalDarkSamples = new Uint32Array(16);
  const regionalPairs = new Uint32Array(16);
  const regionalStrongEdges = new Uint32Array(16);
  const rowPairs = new Uint32Array(gridHeight);
  const rowStrongEdges = new Uint32Array(gridHeight);
  const columnPairs = new Uint32Array(gridWidth);
  const columnStrongEdges = new Uint32Array(gridWidth);
  let samples = 0;
  let lightNeutralSamples = 0;
  let darkSamples = 0;
  let luminanceTotal = 0;
  let luminanceSquaredTotal = 0;

  for (let y = 0, gridY = 0; y < height; y += SAMPLE_STEP, gridY += 1) {
    const normalizedY = (y + 0.5) / height;
    for (let x = 0, gridX = 0; x < width; x += SAMPLE_STEP, gridX += 1) {
      const normalizedX = (x + 0.5) / width;
      if (!isSafeWallSample(normalizedX, normalizedY, face)) continue;

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
      const region = regionalIndex(normalizedX, normalizedY);
      regionalSamples[region] += 1;
      regionalLuminance[region] += luminance;
      if (luminance < 125) regionalDarkSamples[region] += 1;

      // Permit a little more warm/cool cast as exposure rises, while rejecting
      // genuinely coloured walls at every brightness.
      const neutralChromaLimit = Math.min(MAX_NEUTRAL_CHROMA, 22 + luminance * 0.14);
      if (luminance >= MIN_LIGHT_LUMINANCE && chroma <= neutralChromaLimit) {
        lightNeutralSamples += 1;
        zoneLightNeutralSamples[zone] += 1;
        regionalLightNeutralSamples[region] += 1;
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
    const isStrong = luminanceDelta >= 32 || colorDelta >= 42;
    adjacentPairs += 1;
    if (isStrong) strongEdges += 1;
    if (isRough) roughTexturePairs += 1;
    const firstGridX = first % gridWidth;
    const firstGridY = Math.floor(first / gridWidth);
    const region = regionalIndex(
      (firstGridX * SAMPLE_STEP + 0.5) / width,
      (firstGridY * SAMPLE_STEP + 0.5) / height,
    );
    regionalPairs[region] += 1;
    if (isStrong) regionalStrongEdges[region] += 1;
    if (direction === "horizontal") {
      horizontalPairs += 1;
      if (isRough) horizontalRoughTexturePairs += 1;
      columnPairs[firstGridX] += 1;
      if (isStrong) columnStrongEdges[firstGridX] += 1;
    } else {
      verticalPairs += 1;
      if (isRough) verticalRoughTexturePairs += 1;
      rowPairs[firstGridY] += 1;
      if (isStrong) rowStrongEdges[firstGridY] += 1;
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
  const maxLineCoverage = Math.max(
    maximumSupportedRatio(
      columnStrongEdges,
      columnPairs,
      Math.max(12, Math.floor(gridHeight * 0.35)),
    ),
    maximumSupportedRatio(
      rowStrongEdges,
      rowPairs,
      Math.max(8, Math.floor(gridWidth * 0.35)),
    ),
  );
  const maxRegionalEdgeRatio = maximumSupportedRatio(
    regionalStrongEdges,
    regionalPairs,
  );
  const maxRegionalDarkRatio = maximumSupportedRatio(
    regionalDarkSamples,
    regionalSamples,
  );
  let evaluatedZoneCount = 0;
  let failingLightNeutralZoneCount = 0;
  let structuredZoneCount = 0;
  let extremeZoneCount = 0;
  for (let region = 0; region < regionalSamples.length; region += 1) {
    const regionSamples = regionalSamples[region];
    if (regionSamples < 8) continue;
    evaluatedZoneCount += 1;
    const lightNeutralRatio = (
      regionalLightNeutralSamples[region] / regionSamples
    );
    const meanLuminance = regionalLuminance[region] / regionSamples;
    const edgeRatio = regionalPairs[region] >= 4
      ? regionalStrongEdges[region] / regionalPairs[region]
      : 0;
    const darkRatio = regionalDarkSamples[region] / regionSamples;
    if (
      lightNeutralRatio < 0.48
      || meanLuminance < MIN_ZONE_LUMINANCE
    ) {
      failingLightNeutralZoneCount += 1;
    }
    if (
      edgeRatio > MAX_REGIONAL_EDGE_RATIO
      || darkRatio > MAX_REGIONAL_DARK_RATIO
    ) {
      structuredZoneCount += 1;
    }
    if (
      edgeRatio > EXTREME_REGIONAL_EDGE_RATIO
      || darkRatio > EXTREME_REGIONAL_DARK_RATIO
    ) {
      extremeZoneCount += 1;
    }
  }
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
  const availableQuadrantsAreMostlyLightNeutral = zoneSamples.every(
    (count, zone) => (
      count === 0
      || (
        zoneLightNeutralSamples[zone] / count
          >= MIN_ZONE_LIGHT_NEUTRAL_RATIO
        && zoneMeans[zone] >= MIN_ZONE_LUMINANCE
      )
    ),
  );
  const isLightNeutral = lightNeutralRatio >= MIN_LIGHT_NEUTRAL_RATIO
    && averageLuminance >= MIN_AVERAGE_LUMINANCE
    && availableQuadrantsAreMostlyLightNeutral
    && evaluatedZoneCount > 0
    && failingLightNeutralZoneCount <= 1
    && zoneMeanSpread <= MAX_ZONE_MEAN_SPREAD
    && luminanceDeviation <= MAX_LUMINANCE_DEVIATION
    && darkSamples / samples <= MAX_DARK_PIXEL_RATIO;
  const isPlain = withinZoneDeviation <= MAX_WITHIN_ZONE_DEVIATION + 4
    && strongEdgeRatio <= MAX_STRONG_EDGE_RATIO
    && roughTextureRatio <= MAX_ROUGH_TEXTURE_RATIO
    && directionalRoughTextureRatio <= MAX_DIRECTIONAL_ROUGH_TEXTURE_RATIO
    && maxLineCoverage <= MAX_LINE_COVERAGE
    && structuredZoneCount <= 1
    && extremeZoneCount === 0;
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
    maxLineCoverage,
    maxRegionalEdgeRatio,
    maxRegionalDarkRatio,
    evaluatedZoneCount,
    failingLightNeutralZoneCount,
    structuredZoneCount,
    extremeZoneCount,
  };
}

import type {
  CameraValidationOutcome,
} from "../services/camera-quality-policy";

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
  maxLineCoverage: number;
  maxRegionalEdgeRatio: number;
  maxRegionalDarkRatio: number;
  evaluatedZoneCount: number;
  failingLightNeutralZoneCount: number;
  structuredZoneCount: number;
  extremeZoneCount: number;
}

export interface NormalizedPoint {
  x: number;
  y: number;
}

export interface VisaPhotoFaceGeometry {
  centerX: number;
  centerY: number;
  width: number;
  height: number;
  leftEye?: NormalizedPoint;
  rightEye?: NormalizedPoint;
}

export type VisaPhotoFacePlacementStatus =
  | "too_far"
  | "too_close"
  | "off_center"
  | "head_tilt"
  | "ready";

export type VisaPhotoClarityStatus = "good" | "too_dark" | "too_bright" | "blurry";

export interface VisaPhotoClarityMetrics {
  status: VisaPhotoClarityStatus;
  averageLuminance: number;
  darkPixelRatio: number;
  brightPixelRatio: number;
  averageGradient: number;
  highGradientRatio: number;
}

export interface VisaPhotoFallbackCaptureState {
  cameraReady: boolean;
  modelUnavailable: boolean;
  userAcknowledgedRequirements: boolean;
}

export type VisaPhotoFaceCountStatus = "no_face" | "one_face" | "multiple";

export interface VisaPhotoFinalValidation {
  outcome: CameraValidationOutcome;
  message: string;
  faceCount: VisaPhotoFaceCountStatus;
  facePlacement: VisaPhotoFacePlacementStatus | null;
  clarity: VisaPhotoClarityMetrics | null;
  background: WhiteBackgroundMetrics | null;
}

export interface VisaJpegEncoding {
  blob: Blob;
  quality: number;
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
const MAX_LINE_COVERAGE = 0.58;
const MAX_REGIONAL_EDGE_RATIO = 0.25;
const MAX_REGIONAL_DARK_RATIO = 0.36;
const EXTREME_REGIONAL_EDGE_RATIO = 0.55;
const EXTREME_REGIONAL_DARK_RATIO = 0.72;
// The guide itself is 10% smaller, so retaining these guide-relative minima
// produces an approximately 10% smaller on-screen face requirement overall.
const MIN_FACE_WIDTH_RATIO = 0.31;
const MIN_FACE_HEIGHT_RATIO = 0.38;
const MAX_FACE_WIDTH_RATIO = 0.72;
const MAX_FACE_HEIGHT_RATIO = 0.74;
const MAX_FACE_CENTER_X_OFFSET = 0.11;
const MIN_FACE_CENTER_Y = 0.27;
const MAX_FACE_CENTER_Y = 0.52;
const MAX_EYE_LINE_TILT_DEGREES = 12;
const MAX_STABLE_FACE_CENTER_DELTA = 0.045;
const MAX_STABLE_FACE_SIZE_DELTA = 0.055;
const FINAL_HARD_MIN_FACE_WIDTH_RATIO = 0.23;
const FINAL_HARD_MIN_FACE_HEIGHT_RATIO = 0.29;
const FINAL_HARD_MAX_FACE_WIDTH_RATIO = 0.82;
const FINAL_HARD_MAX_FACE_HEIGHT_RATIO = 0.86;
const FINAL_HARD_MAX_FACE_CENTER_X_OFFSET = 0.18;
const FINAL_HARD_MIN_FACE_CENTER_Y = 0.20;
const FINAL_HARD_MAX_FACE_CENTER_Y = 0.62;
const FINAL_HARD_HEAD_EDGE_MARGIN = 0.02;
const FINAL_BORDERLINE_MIN_FACE_GRADIENT = 3.8;
const FINAL_BORDERLINE_MIN_FACE_EDGE_RATIO = 0.028;
const FINAL_BORDERLINE_MIN_FACE_LUMINANCE = 70;
const FINAL_BORDERLINE_MAX_FACE_LUMINANCE = 216;
const FINAL_HARD_MIN_BACKGROUND_LUMINANCE = 115;
const FINAL_HARD_MIN_LIGHT_NEUTRAL_RATIO = 0.35;
const FINAL_HARD_MAX_STRONG_EDGE_RATIO = 0.16;
const FINAL_HARD_MAX_ROUGH_TEXTURE_RATIO = 0.32;
const FINAL_HARD_MAX_LINE_COVERAGE = 0.58;
const FINAL_HARD_MAX_REGIONAL_EDGE_RATIO = 0.42;
const FINAL_HARD_MAX_REGIONAL_DARK_RATIO = 0.55;
export const VISA_JPEG_QUALITY_STEPS = [
  0.94,
  0.9,
  0.85,
  0.8,
  0.74,
] as const;

/**
 * Evaluates wall pixels around the detected head and shoulders.
 *
 * When face geometry is available, a conservative person mask excludes likely
 * hair, ears, clothing, and shoulders while retaining the broader visible wall
 * needed to catch furniture seams and handles. The legacy perimeter strips are
 * retained for callers without geometry. Samples are checked independently for
 * lightness/neutrality, coverage in every quadrant, smooth lighting variation,
 * edge and line density, local dark regions, and high-frequency clutter.
 */
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

export function isVisaSelfieFaceLargeEnough(relativeWidth: number, relativeHeight: number): boolean {
  return relativeWidth >= MIN_FACE_WIDTH_RATIO && relativeHeight >= MIN_FACE_HEIGHT_RATIO;
}

export function evaluateVisaPhotoFaceCount(faceCount: number): VisaPhotoFaceCountStatus {
  if (!Number.isFinite(faceCount) || faceCount <= 0) return "no_face";
  return faceCount === 1 ? "one_face" : "multiple";
}

export function evaluateVisaPhotoFacePlacement(
  face: VisaPhotoFaceGeometry,
): VisaPhotoFacePlacementStatus {
  if (!isVisaSelfieFaceLargeEnough(face.width, face.height)) return "too_far";
  if (face.height > MAX_FACE_HEIGHT_RATIO || face.width > MAX_FACE_WIDTH_RATIO) {
    return "too_close";
  }
  if (
    Math.abs(face.centerX - 0.5) > MAX_FACE_CENTER_X_OFFSET
    || face.centerY < MIN_FACE_CENTER_Y
    || face.centerY > MAX_FACE_CENTER_Y
  ) {
    return "off_center";
  }
  if (face.leftEye && face.rightEye) {
    const eyeLineAngle = Math.atan2(
      Math.abs(face.rightEye.y - face.leftEye.y),
      Math.abs(face.rightEye.x - face.leftEye.x),
    ) * (180 / Math.PI);
    if (eyeLineAngle > MAX_EYE_LINE_TILT_DEGREES) return "head_tilt";
  }
  return "ready";
}

export function isVisaPhotoFaceStable(
  previous: VisaPhotoFaceGeometry | null,
  current: VisaPhotoFaceGeometry,
): boolean {
  if (!previous) return false;
  return (
    Math.abs(previous.centerX - current.centerX)
      <= MAX_STABLE_FACE_CENTER_DELTA
    && Math.abs(previous.centerY - current.centerY)
      <= MAX_STABLE_FACE_CENTER_DELTA
    && Math.abs(previous.width - current.width)
      <= MAX_STABLE_FACE_SIZE_DELTA
    && Math.abs(previous.height - current.height)
      <= MAX_STABLE_FACE_SIZE_DELTA
  );
}

export function evaluateVisaPhotoClarity(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
  face: VisaPhotoFaceGeometry,
): VisaPhotoClarityMetrics {
  // Stay inside the detector's face box so a bright wall around a dark face,
  // or a sharp face/background boundary around an otherwise blurred face,
  // cannot make the facial exposure and sharpness checks look acceptable.
  const bounds = facePixelBounds(face, width, height, 0.38, 0.38);
  if (
    width <= 0
    || height <= 0
    || pixels.length < width * height * 4
    || bounds.right - bounds.left < 3
    || bounds.bottom - bounds.top < 3
  ) {
    return {
      status: "blurry",
      averageLuminance: 0,
      darkPixelRatio: 1,
      brightPixelRatio: 0,
      averageGradient: 0,
      highGradientRatio: 0,
    };
  }

  let samples = 0;
  let luminanceTotal = 0;
  let darkPixels = 0;
  let brightPixels = 0;
  let gradientSamples = 0;
  let gradientTotal = 0;
  let highGradientPixels = 0;
  const faceCenterX = face.centerX * width;
  const faceCenterY = face.centerY * height;
  const faceRadiusX = Math.max(1, face.width * width * 0.38);
  const faceRadiusY = Math.max(1, face.height * height * 0.38);

  for (let y = bounds.top; y <= bounds.bottom; y += 1) {
    for (let x = bounds.left; x <= bounds.right; x += 1) {
      const insideCentralFace = ((x - faceCenterX) / faceRadiusX) ** 2
        + ((y - faceCenterY) / faceRadiusY) ** 2 <= 1;
      if (!insideCentralFace) continue;
      const luminance = pixelLuminance(pixels, width, x, y);
      samples += 1;
      luminanceTotal += luminance;
      if (luminance < 32) darkPixels += 1;
      if (luminance > 246) brightPixels += 1;
      if (
        x <= bounds.left
        || x >= bounds.right
        || y <= bounds.top
        || y >= bounds.bottom
      ) {
        continue;
      }
      const horizontal = Math.abs(
        pixelLuminance(pixels, width, x + 1, y)
        - pixelLuminance(pixels, width, x - 1, y),
      );
      const vertical = Math.abs(
        pixelLuminance(pixels, width, x, y + 1)
        - pixelLuminance(pixels, width, x, y - 1),
      );
      const gradient = (horizontal + vertical) / 2;
      gradientSamples += 1;
      gradientTotal += gradient;
      if (gradient >= 24) highGradientPixels += 1;
    }
  }

  const averageLuminance = luminanceTotal / Math.max(1, samples);
  const darkPixelRatio = darkPixels / Math.max(1, samples);
  const brightPixelRatio = brightPixels / Math.max(1, samples);
  const averageGradient = gradientTotal / Math.max(1, gradientSamples);
  const highGradientRatio = highGradientPixels / Math.max(1, gradientSamples);
  const status: VisaPhotoClarityStatus = averageLuminance < 58 && darkPixelRatio > 0.34
    ? "too_dark"
    : averageLuminance > 226 && brightPixelRatio > 0.34
      ? "too_bright"
      : averageGradient < 2.8 && highGradientRatio < 0.018
        ? "blurry"
        : "good";

  return {
    status,
    averageLuminance,
    darkPixelRatio,
    brightPixelRatio,
    averageGradient,
    highGradientRatio,
  };
}

/**
 * Classifies the exact, encoded Visa Photo pixels after a fresh face-detection
 * pass. Only definite capture failures are hard stops; near-threshold quality
 * remains reviewable after an explicit user confirmation.
 */
export function evaluateFinalVisaPhoto({
  faceCount,
  face,
  pixels,
  width,
  height,
}: {
  faceCount: number;
  face: VisaPhotoFaceGeometry | null;
  pixels: Uint8ClampedArray;
  width: number;
  height: number;
}): VisaPhotoFinalValidation {
  const countStatus = evaluateVisaPhotoFaceCount(faceCount);
  if (countStatus === "no_face") {
    return finalValidation(
      "hard_failure",
      "No face was found in the captured photo. Retake with your full head inside the guide.",
      countStatus,
    );
  }
  if (countStatus === "multiple") {
    return finalValidation(
      "hard_failure",
      "More than one face is visible. Retake the photo with only one person in frame.",
      countStatus,
    );
  }
  if (!face) {
    return finalValidation(
      "hard_failure",
      "The captured face position could not be checked. Retake the photo.",
      countStatus,
    );
  }

  const liveFacePlacement = evaluateVisaPhotoFacePlacement(face);
  const hardFacePlacement = definiteFinalFacePlacementFailure(face);
  const facePlacement = hardFacePlacement ?? liveFacePlacement;
  const clarity = evaluateVisaPhotoClarity(pixels, width, height, face);
  const background = evaluateWhiteBackground(
    pixels,
    width,
    height,
    face,
  );
  if (hardFacePlacement) {
    const message = hardFacePlacement === "too_far"
      ? "Your face is too small in the captured photo. Move closer and retake it."
      : hardFacePlacement === "too_close"
        ? "Part of your head may be cut off. Move back slightly and retake the photo."
        : "Your head moved outside the centre of the guide. Retake the photo.";
    return finalValidation(
      "hard_failure",
      message,
      countStatus,
      facePlacement,
      clarity,
      background,
    );
  }
  if (clarity.status === "blurry") {
    return finalValidation(
      "hard_failure",
      "Your face is severely blurred in the captured photo. Hold steady and retake it.",
      countStatus,
      facePlacement,
      clarity,
      background,
    );
  }
  if (clarity.status === "too_dark") {
    return finalValidation(
      "hard_failure",
      "Your face is too dark in the captured photo. Move into brighter, even light and retake it.",
      countStatus,
      facePlacement,
      clarity,
      background,
    );
  }
  if (clarity.status === "too_bright") {
    return finalValidation(
      "hard_failure",
      "Your face is severely overexposed. Move away from harsh light and retake the photo.",
      countStatus,
      facePlacement,
      clarity,
      background,
    );
  }
  if (isDefinitelyInvalidBackground(background)) {
    return finalValidation(
      "hard_failure",
      background.isLightNeutral
        ? "The captured background contains a strong pattern, line, or object. Use a plain light wall and retake the photo."
        : "The captured background is too dark or strongly coloured. Use a white, off-white, or light-neutral wall and retake the photo.",
      countStatus,
      facePlacement,
      clarity,
      background,
    );
  }

  const slightlySoft = (
    clarity.averageGradient < FINAL_BORDERLINE_MIN_FACE_GRADIENT
    && clarity.highGradientRatio < FINAL_BORDERLINE_MIN_FACE_EDGE_RATIO
  );
  const unevenFaceLighting = (
    clarity.averageLuminance < FINAL_BORDERLINE_MIN_FACE_LUMINANCE
    || clarity.averageLuminance > FINAL_BORDERLINE_MAX_FACE_LUMINANCE
  );
  if (
    facePlacement !== "ready"
    || !background.isWhite
    || slightlySoft
    || unevenFaceLighting
  ) {
    const message = facePlacement !== "ready"
      ? facePlacement === "head_tilt"
        ? "Your head is slightly tilted. Confirm the photo is clear and acceptable, or retake it."
        : "Your face moved close to the placement limit. Confirm your full head is visible and centred, or retake the photo."
      : !background.isWhite
        ? "The background is close to the limit for colour or texture. Confirm it is a plain light wall, or retake the photo."
        : slightlySoft
          ? "Your face is slightly soft. Confirm your eyes and facial details are clear, or retake the photo."
          : "The facial lighting is uneven. Confirm all facial details remain clear, or retake the photo.";
    return finalValidation(
      "borderline",
      message,
      countStatus,
      facePlacement,
      clarity,
      background,
    );
  }

  return finalValidation(
    "pass",
    "Visa Photo checks passed.",
    countStatus,
    facePlacement,
    clarity,
    background,
  );
}

/**
 * When the face model is unavailable, validate every pixel signal that remains
 * measurable on the exact JPEG. Face count and geometry stay explicitly
 * unverified, so a non-failing result can only be borderline.
 */
export function evaluateFallbackFinalVisaPhoto({
  pixels,
  width,
  height,
}: {
  pixels: Uint8ClampedArray;
  width: number;
  height: number;
}): VisaPhotoFinalValidation {
  const approximateGuideFace: VisaPhotoFaceGeometry = {
    centerX: 0.5,
    centerY: 0.4,
    width: 0.4,
    height: 0.5,
  };
  const availableChecks = evaluateFinalVisaPhoto({
    faceCount: 1,
    face: approximateGuideFace,
    pixels,
    width,
    height,
  });
  if (availableChecks.outcome === "hard_failure") {
    return {
      ...availableChecks,
      faceCount: "no_face",
      facePlacement: null,
    };
  }
  return finalValidation(
    "borderline",
    "Automatic face count and placement checks were unavailable. The exact photo passed the available lighting, clarity, and background checks; confirm there is one clear, centred face with open eyes.",
    "no_face",
    null,
    availableChecks.clarity,
    availableChecks.background,
  );
}

function definiteFinalFacePlacementFailure(
  face: VisaPhotoFaceGeometry,
): Exclude<VisaPhotoFacePlacementStatus, "head_tilt" | "ready"> | null {
  const top = face.centerY - face.height / 2;
  const bottom = face.centerY + face.height / 2;
  if (
    top < FINAL_HARD_HEAD_EDGE_MARGIN
    || bottom > 1 - FINAL_HARD_HEAD_EDGE_MARGIN
    || face.width > FINAL_HARD_MAX_FACE_WIDTH_RATIO
    || face.height > FINAL_HARD_MAX_FACE_HEIGHT_RATIO
  ) {
    return "too_close";
  }
  if (
    face.width < FINAL_HARD_MIN_FACE_WIDTH_RATIO
    || face.height < FINAL_HARD_MIN_FACE_HEIGHT_RATIO
  ) {
    return "too_far";
  }
  if (
    Math.abs(face.centerX - 0.5)
      > FINAL_HARD_MAX_FACE_CENTER_X_OFFSET
    || face.centerY < FINAL_HARD_MIN_FACE_CENTER_Y
    || face.centerY > FINAL_HARD_MAX_FACE_CENTER_Y
  ) {
    return "off_center";
  }
  return null;
}

/**
 * Tries progressively smaller JPEG encodings of the same already-sized canvas.
 * The exclusive byte cap is checked against the actual Blob returned by the
 * browser; no second crop, resize, smoothing, or sharpening is performed.
 */
export async function encodeVisaJpegUnderLimit(
  encode: (quality: number) => Promise<Blob>,
  byteLimit: number,
): Promise<VisaJpegEncoding> {
  for (const quality of VISA_JPEG_QUALITY_STEPS) {
    const blob = await encode(quality);
    if (blob.size > 0 && blob.size < byteLimit) {
      return { blob, quality };
    }
  }
  throw new Error("The Visa Photo could not be kept below 2 MB. Retake it in steadier lighting.");
}

function isDefinitelyInvalidBackground(
  background: WhiteBackgroundMetrics,
): boolean {
  if (
    !background.isLightNeutral
    && (
      background.averageLuminance < FINAL_HARD_MIN_BACKGROUND_LUMINANCE
      || background.lightNeutralRatio < FINAL_HARD_MIN_LIGHT_NEUTRAL_RATIO
      || background.failingLightNeutralZoneCount >= 2
    )
  ) {
    return true;
  }
  return (
    background.strongEdgeRatio > FINAL_HARD_MAX_STRONG_EDGE_RATIO
    || background.roughTextureRatio > FINAL_HARD_MAX_ROUGH_TEXTURE_RATIO
    || background.maxLineCoverage > FINAL_HARD_MAX_LINE_COVERAGE
    || background.structuredZoneCount >= 2
    || background.extremeZoneCount >= 1
    || (
      background.maxRegionalEdgeRatio
        > FINAL_HARD_MAX_REGIONAL_EDGE_RATIO
      && background.maxRegionalDarkRatio
        > FINAL_HARD_MAX_REGIONAL_DARK_RATIO
    )
  );
}

function finalValidation(
  outcome: CameraValidationOutcome,
  message: string,
  faceCount: VisaPhotoFaceCountStatus,
  facePlacement: VisaPhotoFacePlacementStatus | null = null,
  clarity: VisaPhotoClarityMetrics | null = null,
  background: WhiteBackgroundMetrics | null = null,
): VisaPhotoFinalValidation {
  return {
    outcome,
    message,
    faceCount,
    facePlacement,
    clarity,
    background,
  };
}

export function isVisaPhotoFrameCaptureReady(
  backgroundStatus: "checking" | "white" | "not_white" | "not_plain",
  clarityStatus: "checking" | VisaPhotoClarityStatus,
): boolean {
  return backgroundStatus === "white"
    && clarityStatus === "good";
}

export function isVisaPhotoFallbackCaptureAllowed({
  cameraReady,
  modelUnavailable,
  userAcknowledgedRequirements,
}: VisaPhotoFallbackCaptureState): boolean {
  return cameraReady
    && modelUnavailable
    && userAcknowledgedRequirements;
}

export function buildVisaPhotoCameraConstraints(
  preferRearCamera = true,
): MediaStreamConstraints {
  return {
    video: {
      ...(preferRearCamera ? { facingMode: { ideal: "environment" } } : {}),
      width: { ideal: 1920 },
      height: { ideal: 1440 },
    },
    audio: false,
  };
}

export async function requestVisaPhotoCamera<T>(
  getUserMedia: (constraints: MediaStreamConstraints) => Promise<T>,
): Promise<T> {
  try {
    return await getUserMedia(buildVisaPhotoCameraConstraints(true));
  } catch (error) {
    const errorName = cameraErrorName(error);
    if (errorName === "NotAllowedError" || errorName === "SecurityError") {
      throw error;
    }
    // facingMode is only a preference and is inconsistently implemented by
    // desktop and in-app browsers. A second request without lens selection
    // preserves a usable camera path without exposing a camera selector.
    return getUserMedia(buildVisaPhotoCameraConstraints(false));
  }
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
 * Selects pixels expected to be visible wall. Face-aware callers use the wider
 * detected-person mask; callers without geometry retain conservative perimeter
 * strips that tolerate untidy hair and broad shoulders.
 */
function isSafeWallSample(
  x: number,
  y: number,
  face?: VisaPhotoFaceGeometry,
): boolean {
  if (face) {
    if (y >= 0.9) return false;
    return !isInsideDetectedPersonMask(x, y, face);
  }
  // The lower portion is intentionally omitted: with the requested close crop,
  // shoulders and clothing legitimately reach both frame edges there.
  if (y >= 0.62) return false;
  if (y < 0.40) return x <= 0.06 || x >= 0.94;
  if (y < 0.58) return x <= 0.10 || x >= 0.90;
  return x <= 0.06 || x >= 0.94;
}

function isInsideDetectedPersonMask(
  x: number,
  y: number,
  face: VisaPhotoFaceGeometry,
): boolean {
  const headRadiusX = Math.max(0.18, face.width * 0.72);
  const headRadiusY = Math.max(0.24, face.height * 0.68);
  const inHead = ((x - face.centerX) / headRadiusX) ** 2
    + ((y - face.centerY) / headRadiusY) ** 2 <= 1;
  if (inHead) return true;

  const shoulderStart = face.centerY + face.height * 0.34;
  if (y < shoulderStart) return false;
  const progress = Math.min(1, Math.max(0, (y - shoulderStart) / 0.42));
  const shoulderHalfWidth = Math.min(
    0.5,
    Math.max(0.22, face.width * 0.82) + progress * 0.28,
  );
  return Math.abs(x - face.centerX) <= shoulderHalfWidth;
}

function regionalIndex(x: number, y: number): number {
  const column = Math.min(3, Math.max(0, Math.floor(x * 4)));
  const row = Math.min(3, Math.max(0, Math.floor(y * 4)));
  return row * 4 + column;
}

function maximumSupportedRatio(
  numerators: ArrayLike<number>,
  denominators: ArrayLike<number>,
  minimumSupport = 4,
): number {
  let maximum = 0;
  for (let index = 0; index < denominators.length; index += 1) {
    const denominator = denominators[index];
    if (denominator < minimumSupport) continue;
    maximum = Math.max(maximum, numerators[index] / denominator);
  }
  return maximum;
}

interface PixelBounds {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

function facePixelBounds(
  face: VisaPhotoFaceGeometry,
  width: number,
  height: number,
  horizontalScale: number,
  verticalScale: number,
): PixelBounds {
  return {
    left: clampPixel((face.centerX - face.width * horizontalScale) * width, width),
    right: clampPixel((face.centerX + face.width * horizontalScale) * width, width),
    top: clampPixel((face.centerY - face.height * verticalScale) * height, height),
    bottom: clampPixel((face.centerY + face.height * verticalScale) * height, height),
  };
}

function clampPixel(value: number, extent: number): number {
  return Math.min(extent - 1, Math.max(0, Math.round(value)));
}

function pixelLuminance(
  pixels: Uint8ClampedArray,
  width: number,
  x: number,
  y: number,
): number {
  const index = (y * width + x) * 4;
  return 0.2126 * pixels[index]
    + 0.7152 * pixels[index + 1]
    + 0.0722 * pixels[index + 2];
}

function cameraErrorName(error: unknown): string | null {
  if (!error || typeof error !== "object" || !("name" in error)) return null;
  const name = (error as { name?: unknown }).name;
  return typeof name === "string" ? name : null;
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
    maxLineCoverage: 1,
    maxRegionalEdgeRatio: 1,
    maxRegionalDarkRatio: 1,
    evaluatedZoneCount: 0,
    failingLightNeutralZoneCount: 0,
    structuredZoneCount: 0,
    extremeZoneCount: 0,
  };
}

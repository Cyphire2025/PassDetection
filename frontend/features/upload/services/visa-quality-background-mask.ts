import type { WhiteBackgroundMetrics, VisaPhotoFaceGeometry } from "./visa-quality.types.ts";

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
export function isSafeWallSample(
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

export function regionalIndex(x: number, y: number): number {
  const column = Math.min(3, Math.max(0, Math.floor(x * 4)));
  const row = Math.min(3, Math.max(0, Math.floor(y * 4)));
  return row * 4 + column;
}

export function maximumSupportedRatio(
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

export function failedMetrics(): WhiteBackgroundMetrics {
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

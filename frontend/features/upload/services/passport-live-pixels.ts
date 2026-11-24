import type { RectangularPassportFrameStatus, RectangularPassportFrameResult } from "./passport-live.types.ts";
import { PASSPORT_LIVE_THRESHOLDS } from "./passport-live-policy.ts";
import { roundMetric } from "./camera-pixel-math.ts";

export function createMotionSignature(
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

export function analyzeExposure(gray: Uint8Array) {
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

export function emptyResult(
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

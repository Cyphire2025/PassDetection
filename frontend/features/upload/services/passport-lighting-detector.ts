import { getPassportAnalysisBounds } from "./passport-analysis-region";

export type LightingStatus = "good" | "too_dark" | "too_bright";

export interface LightingDetectionResult {
  status: LightingStatus;
  isWellLit: boolean;
  meanLuminance: number;
  darkPixelRatio: number;
  brightPixelRatio: number;
  contrast: number;
}

const SAMPLE_WIDTH = 256;
const SAMPLE_HEIGHT = 160;
const DARK_PIXEL_THRESHOLD = 52;
const BRIGHT_PIXEL_THRESHOLD = 228;

/**
 * Phase 8: estimates exposure quality inside the passport guide region.
 * Glare and perspective remain separate later phases.
 */
export function detectPassportLighting(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement,
): LightingDetectionResult {
  if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || !video.videoWidth) {
    return emptyLightingResult();
  }

  canvas.width = SAMPLE_WIDTH;
  canvas.height = SAMPLE_HEIGHT;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return emptyLightingResult();

  context.drawImage(video, 0, 0, SAMPLE_WIDTH, SAMPLE_HEIGHT);
  const { data } = context.getImageData(0, 0, SAMPLE_WIDTH, SAMPLE_HEIGHT);
  const bounds = getPassportAnalysisBounds(SAMPLE_WIDTH, SAMPLE_HEIGHT);

  let sum = 0;
  let squaredSum = 0;
  let darkPixels = 0;
  let brightPixels = 0;
  let samples = 0;

  for (let y = bounds.top; y < bounds.bottom; y += 1) {
    for (let x = bounds.left; x < bounds.right; x += 1) {
      const index = (y * SAMPLE_WIDTH + x) * 4;
      const luminance = data[index] * 0.299 + data[index + 1] * 0.587 + data[index + 2] * 0.114;
      sum += luminance;
      squaredSum += luminance * luminance;
      if (luminance <= DARK_PIXEL_THRESHOLD) darkPixels += 1;
      if (luminance >= BRIGHT_PIXEL_THRESHOLD) brightPixels += 1;
      samples += 1;
    }
  }

  if (!samples) return emptyLightingResult();

  const meanLuminance = sum / samples;
  const variance = Math.max(0, squaredSum / samples - meanLuminance * meanLuminance);
  const contrast = Math.sqrt(variance);
  const darkPixelRatio = darkPixels / samples;
  const brightPixelRatio = brightPixels / samples;

  const status: LightingStatus =
    meanLuminance < 92 || darkPixelRatio > 0.42 || (meanLuminance < 112 && contrast < 36)
      ? "too_dark"
      : meanLuminance > 198 || brightPixelRatio > 0.2
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

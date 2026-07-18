import {
  evaluatePassportLightingPixels,
  type LightingDetectionResult,
  type LightingStatus,
} from "./passport-scanner-quality";
import { drawPassportGuideFrame } from "./passport-frame-detector";

export type { LightingDetectionResult, LightingStatus };
export { evaluatePassportLightingPixels };

const SAMPLE_WIDTH = 256;
const SAMPLE_HEIGHT = 180;

/** Estimates exposure quality inside the passport guide region. */
export function detectPassportLighting(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement,
  guide: HTMLElement | null = null,
): LightingDetectionResult {
  if (!drawPassportGuideFrame(
    video,
    canvas,
    guide,
    SAMPLE_WIDTH,
    SAMPLE_HEIGHT,
  )) {
    return emptyLightingResult();
  }
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return emptyLightingResult();
  const { data } = context.getImageData(0, 0, SAMPLE_WIDTH, SAMPLE_HEIGHT);
  return evaluatePassportLightingPixels(data, SAMPLE_WIDTH, SAMPLE_HEIGHT);
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

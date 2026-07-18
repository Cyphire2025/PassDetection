import {
  evaluatePassportGlarePixels,
  type GlareDetectionResult,
} from "./passport-scanner-quality";
import { drawPassportGuideFrame } from "./passport-frame-detector";

export type { GlareDetectionResult };
export { evaluatePassportGlarePixels };

const SAMPLE_WIDTH = 256;
const SAMPLE_HEIGHT = 180;

/** Estimates whether specular reflection covers meaningful passport area. */
export function detectPassportGlare(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement,
  guide: HTMLElement | null = null,
): GlareDetectionResult {
  if (!drawPassportGuideFrame(
    video,
    canvas,
    guide,
    SAMPLE_WIDTH,
    SAMPLE_HEIGHT,
  )) {
    return emptyGlareResult();
  }
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return emptyGlareResult();
  const { data } = context.getImageData(0, 0, SAMPLE_WIDTH, SAMPLE_HEIGHT);
  return evaluatePassportGlarePixels(data, SAMPLE_WIDTH, SAMPLE_HEIGHT);
}

function emptyGlareResult(): GlareDetectionResult {
  return {
    hasGlare: false,
    highlightRatio: 0,
    largestClusterRatio: 0,
  };
}

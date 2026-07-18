import {
  evaluatePassportBlurPixels,
  type BlurDetectionResult,
} from "./passport-scanner-quality";
import { drawPassportGuideFrame } from "./passport-frame-detector";

export type { BlurDetectionResult };
export { evaluatePassportBlurPixels };

const SAMPLE_WIDTH = 256;
const SAMPLE_HEIGHT = 180;

/** Estimates focus quality using variance of the discrete Laplacian. */
export function detectPassportBlur(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement,
  guide: HTMLElement | null = null,
): BlurDetectionResult {
  if (!drawPassportGuideFrame(
    video,
    canvas,
    guide,
    SAMPLE_WIDTH,
    SAMPLE_HEIGHT,
  )) {
    return { isSharp: false, score: 0 };
  }
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return { isSharp: false, score: 0 };
  const { data } = context.getImageData(0, 0, SAMPLE_WIDTH, SAMPLE_HEIGHT);
  return evaluatePassportBlurPixels(data, SAMPLE_WIDTH, SAMPLE_HEIGHT);
}

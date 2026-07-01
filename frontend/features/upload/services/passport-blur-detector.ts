import { getPassportAnalysisBounds } from "./passport-analysis-region";

export interface BlurDetectionResult {
  isSharp: boolean;
  score: number;
}

const SAMPLE_WIDTH = 256;
const SAMPLE_HEIGHT = 160;
const SHARPNESS_THRESHOLD = 115;

/** Estimates focus quality using variance of the discrete Laplacian. */
export function detectPassportBlur(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement,
): BlurDetectionResult {
  if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || !video.videoWidth) {
    return { isSharp: false, score: 0 };
  }

  canvas.width = SAMPLE_WIDTH;
  canvas.height = SAMPLE_HEIGHT;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return { isSharp: false, score: 0 };

  context.drawImage(video, 0, 0, SAMPLE_WIDTH, SAMPLE_HEIGHT);
  const { data } = context.getImageData(0, 0, SAMPLE_WIDTH, SAMPLE_HEIGHT);
  const gray = new Float32Array(SAMPLE_WIDTH * SAMPLE_HEIGHT);
  for (let pixel = 0, index = 0; pixel < gray.length; pixel += 1, index += 4) {
    gray[pixel] = data[index] * 0.299 + data[index + 1] * 0.587 + data[index + 2] * 0.114;
  }

  // Analyze only the guide region so a detailed background cannot hide blur.
  const { left, right, top, bottom } = getPassportAnalysisBounds(SAMPLE_WIDTH, SAMPLE_HEIGHT);
  let sum = 0;
  let squaredSum = 0;
  let samples = 0;

  for (let y = top + 1; y < bottom - 1; y += 1) {
    for (let x = left + 1; x < right - 1; x += 1) {
      const center = y * SAMPLE_WIDTH + x;
      const laplacian = gray[center - 1] + gray[center + 1]
        + gray[center - SAMPLE_WIDTH] + gray[center + SAMPLE_WIDTH]
        - 4 * gray[center];
      sum += laplacian;
      squaredSum += laplacian * laplacian;
      samples += 1;
    }
  }

  if (!samples) return { isSharp: false, score: 0 };
  const mean = sum / samples;
  const variance = Math.max(0, squaredSum / samples - mean * mean);
  const score = Math.round(variance);
  return { isSharp: score >= SHARPNESS_THRESHOLD, score };
}

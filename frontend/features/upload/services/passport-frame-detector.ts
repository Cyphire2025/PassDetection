import { getPassportAnalysisBounds } from "./passport-analysis-region";

export interface FrameDetectionResult {
  isDetected: boolean;
  confidence: number;
  visibleEdges: number;
}

const SAMPLE_WIDTH = 320;
const SAMPLE_HEIGHT = 200;
const EDGE_THRESHOLD = 42;

/**
 * Detects whether a document-shaped boundary is visible near the capture guide.
 * This intentionally returns geometry only; blur, glare, and lighting belong to
 * later quality-analysis phases.
 */
export function detectPassportFrame(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement,
): FrameDetectionResult {
  if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || !video.videoWidth) {
    return { isDetected: false, confidence: 0, visibleEdges: 0 };
  }

  canvas.width = SAMPLE_WIDTH;
  canvas.height = SAMPLE_HEIGHT;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return { isDetected: false, confidence: 0, visibleEdges: 0 };

  context.drawImage(video, 0, 0, SAMPLE_WIDTH, SAMPLE_HEIGHT);
  const { data } = context.getImageData(0, 0, SAMPLE_WIDTH, SAMPLE_HEIGHT);
  const gray = new Uint8Array(SAMPLE_WIDTH * SAMPLE_HEIGHT);
  for (let pixel = 0, index = 0; pixel < gray.length; pixel += 1, index += 4) {
    gray[pixel] = Math.round(data[index] * 0.299 + data[index + 1] * 0.587 + data[index + 2] * 0.114);
  }

  // The guide occupies the central 72% x 64% of the preview. A passport is
  // considered present when strong gradients appear on at least three sides.
  const { left, right, top, bottom } = getPassportAnalysisBounds(SAMPLE_WIDTH, SAMPLE_HEIGHT);
  const band = 8;

  const verticalScore = (center: number) => {
    let edges = 0;
    let samples = 0;
    for (let y = top; y <= bottom; y += 2) {
      for (let x = center - band; x <= center + band; x += 2) {
        const offset = y * SAMPLE_WIDTH + x;
        if (Math.abs(gray[offset + 1] - gray[offset - 1]) > EDGE_THRESHOLD) edges += 1;
        samples += 1;
      }
    }
    return edges / samples;
  };

  const horizontalScore = (center: number) => {
    let edges = 0;
    let samples = 0;
    for (let y = center - band; y <= center + band; y += 2) {
      for (let x = left; x <= right; x += 2) {
        const offset = y * SAMPLE_WIDTH + x;
        if (Math.abs(gray[offset + SAMPLE_WIDTH] - gray[offset - SAMPLE_WIDTH]) > EDGE_THRESHOLD) edges += 1;
        samples += 1;
      }
    }
    return edges / samples;
  };

  const scores = [verticalScore(left), verticalScore(right), horizontalScore(top), horizontalScore(bottom)];
  const visibleEdges = scores.filter((score) => score >= 0.035).length;
  const confidence = Math.min(1, scores.reduce((sum, score) => sum + score, 0) / 0.22);
  return { isDetected: visibleEdges >= 3, confidence, visibleEdges };
}

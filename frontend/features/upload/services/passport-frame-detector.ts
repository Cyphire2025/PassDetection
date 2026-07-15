import { getPassportAnalysisBounds } from "./passport-analysis-region";

export interface FrameDetectionResult {
  isDetected: boolean;
  confidence: number;
  visibleEdges: number;
}

const SAMPLE_WIDTH = 320;
const SAMPLE_HEIGHT = 200;
const EDGE_THRESHOLD = 30;

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

  const { left, right, top, bottom } = getPassportAnalysisBounds(SAMPLE_WIDTH, SAMPLE_HEIGHT);
  const guideHeight = bottom - top;
  const band = 10;

  const guideStats = (() => {
    let samples = 0;
    let brightPixels = 0;
    let gradientPixels = 0;
    let darkMrzPixels = 0;
    let guideSum = 0;
    const mrzTop = top + Math.round(guideHeight * 0.68);
    for (let y = top; y <= bottom; y += 2) {
      for (let x = left; x <= right; x += 2) {
        const offset = y * SAMPLE_WIDTH + x;
        const value = gray[offset];
        guideSum += value;
        if (value > 88) brightPixels += 1;
        const gradient = Math.abs(gray[offset + 1] - gray[offset - 1])
          + Math.abs(gray[offset + SAMPLE_WIDTH] - gray[offset - SAMPLE_WIDTH]);
        if (gradient > EDGE_THRESHOLD) gradientPixels += 1;
        if (y >= mrzTop && value < 118 && gradient > 18) darkMrzPixels += 1;
        samples += 1;
      }
    }

    return {
      brightness: guideSum / Math.max(1, samples) / 255,
      brightRatio: brightPixels / Math.max(1, samples),
      textureRatio: gradientPixels / Math.max(1, samples),
      mrzTextureRatio: darkMrzPixels / Math.max(1, samples),
    };
  })();

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

  const boundaryScores = [verticalScore(left), verticalScore(right), horizontalScore(top), horizontalScore(bottom)];
  const visibleEdges = boundaryScores.filter((score) => score >= 0.026).length;
  const boundaryConfidence = Math.min(1, boundaryScores.reduce((sum, score) => sum + score, 0) / 0.12);
  const fillConfidence = Math.min(1, guideStats.brightRatio / 0.7);
  const textConfidence = Math.min(1, guideStats.textureRatio / 0.12);
  const mrzConfidence = Math.min(1, guideStats.mrzTextureRatio / 0.022);
  const exposureConfidence = guideStats.brightness > 0.32 && guideStats.brightness < 0.9 ? 1 : 0.5;
  const confidence = Math.min(
    1,
    (fillConfidence * 0.34)
      + (textConfidence * 0.28)
      + (mrzConfidence * 0.26)
      + (boundaryConfidence * 0.07)
      + (exposureConfidence * 0.05),
  );

  return {
    isDetected: guideStats.brightRatio >= 0.62
      && guideStats.textureRatio >= 0.08
      && guideStats.mrzTextureRatio >= 0.014
      && confidence >= 0.68,
    confidence,
    visibleEdges,
  };
}

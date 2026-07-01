import { getPassportAnalysisBounds } from "./passport-analysis-region";

export interface GlareDetectionResult {
  hasGlare: boolean;
  highlightRatio: number;
  largestClusterRatio: number;
}

const SAMPLE_WIDTH = 256;
const SAMPLE_HEIGHT = 160;
const HIGHLIGHT_LUMINANCE_THRESHOLD = 242;
const HIGHLIGHT_CLUSTER_THRESHOLD = 0.028;
const HIGHLIGHT_RATIO_THRESHOLD = 0.11;

/**
 * Phase 9: estimates whether a specular reflection is covering meaningful
 * passport area. This stays separate from global lighting analysis.
 */
export function detectPassportGlare(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement,
): GlareDetectionResult {
  if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || !video.videoWidth) {
    return emptyGlareResult();
  }

  canvas.width = SAMPLE_WIDTH;
  canvas.height = SAMPLE_HEIGHT;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return emptyGlareResult();

  context.drawImage(video, 0, 0, SAMPLE_WIDTH, SAMPLE_HEIGHT);
  const { data } = context.getImageData(0, 0, SAMPLE_WIDTH, SAMPLE_HEIGHT);
  const bounds = getPassportAnalysisBounds(SAMPLE_WIDTH, SAMPLE_HEIGHT);

  const roiWidth = Math.max(1, bounds.right - bounds.left);
  const roiHeight = Math.max(1, bounds.bottom - bounds.top);
  const totalPixels = roiWidth * roiHeight;
  const highlights = new Uint8Array(totalPixels);

  let highlightPixels = 0;
  let pointer = 0;

  for (let y = bounds.top; y < bounds.bottom; y += 1) {
    for (let x = bounds.left; x < bounds.right; x += 1) {
      const index = (y * SAMPLE_WIDTH + x) * 4;
      const red = data[index];
      const green = data[index + 1];
      const blue = data[index + 2];
      const luminance = red * 0.299 + green * 0.587 + blue * 0.114;
      const channelSpread = Math.max(red, green, blue) - Math.min(red, green, blue);
      const isHighlight = luminance >= HIGHLIGHT_LUMINANCE_THRESHOLD && channelSpread <= 26;

      if (isHighlight) {
        highlights[pointer] = 1;
        highlightPixels += 1;
      }

      pointer += 1;
    }
  }

  const largestCluster = findLargestHighlightCluster(highlights, roiWidth, roiHeight);
  const highlightRatio = highlightPixels / totalPixels;
  const largestClusterRatio = largestCluster / totalPixels;

  return {
    hasGlare:
      largestClusterRatio >= HIGHLIGHT_CLUSTER_THRESHOLD
      || highlightRatio >= HIGHLIGHT_RATIO_THRESHOLD,
    highlightRatio: Number(highlightRatio.toFixed(3)),
    largestClusterRatio: Number(largestClusterRatio.toFixed(3)),
  };
}

function findLargestHighlightCluster(highlights: Uint8Array, width: number, height: number): number {
  const visited = new Uint8Array(highlights.length);
  let largestCluster = 0;

  for (let index = 0; index < highlights.length; index += 1) {
    if (!highlights[index] || visited[index]) continue;

    let clusterSize = 0;
    const queue = [index];
    visited[index] = 1;

    while (queue.length > 0) {
      const current = queue.pop();
      if (current === undefined) continue;

      clusterSize += 1;
      const x = current % width;
      const y = Math.floor(current / width);

      for (let offsetY = -1; offsetY <= 1; offsetY += 1) {
        for (let offsetX = -1; offsetX <= 1; offsetX += 1) {
          if (offsetX === 0 && offsetY === 0) continue;

          const nextX = x + offsetX;
          const nextY = y + offsetY;
          if (nextX < 0 || nextX >= width || nextY < 0 || nextY >= height) continue;

          const nextIndex = nextY * width + nextX;
          if (!highlights[nextIndex] || visited[nextIndex]) continue;

          visited[nextIndex] = 1;
          queue.push(nextIndex);
        }
      }
    }

    largestCluster = Math.max(largestCluster, clusterSize);
  }

  return largestCluster;
}

function emptyGlareResult(): GlareDetectionResult {
  return {
    hasGlare: false,
    highlightRatio: 0,
    largestClusterRatio: 0,
  };
}

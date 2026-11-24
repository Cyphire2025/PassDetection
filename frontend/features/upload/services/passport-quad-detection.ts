import type { Point, DocumentQuad, FittedLine } from "./passport-normalization.types.ts";
import { toGrayscale } from "./camera-pixel-math.ts";
import { fitRobustLine } from "./passport-line-fitting.ts";
import { intersectVerticalAndHorizontal, isPlausibleQuad, scalePoint } from "./passport-quad-geometry.ts";

const ANALYSIS_MAX_WIDTH = 520;

export function detectDocumentQuad(source: HTMLCanvasElement): DocumentQuad | null {
  if (source.width < 160 || source.height < 100) return null;

  const analysis = document.createElement("canvas");
  const scale = Math.min(1, ANALYSIS_MAX_WIDTH / source.width);
  analysis.width = Math.max(160, Math.round(source.width * scale));
  analysis.height = Math.max(100, Math.round(source.height * scale));
  const context = analysis.getContext("2d", { willReadFrequently: true });
  if (!context) return null;
  context.drawImage(source, 0, 0, analysis.width, analysis.height);

  const pixels = context.getImageData(0, 0, analysis.width, analysis.height).data;
  const gray = toGrayscale(pixels, analysis.width, analysis.height);
  const left = fitVerticalBoundary(gray, analysis.width, analysis.height, "left");
  const right = fitVerticalBoundary(gray, analysis.width, analysis.height, "right");
  const top = fitHorizontalBoundary(gray, analysis.width, analysis.height, "top");
  const bottom = fitHorizontalBoundary(gray, analysis.width, analysis.height, "bottom");
  if (!left || !right || !top || !bottom) return null;

  const analysisQuad: DocumentQuad = {
    topLeft: intersectVerticalAndHorizontal(left, top),
    topRight: intersectVerticalAndHorizontal(right, top),
    bottomRight: intersectVerticalAndHorizontal(right, bottom),
    bottomLeft: intersectVerticalAndHorizontal(left, bottom),
  };
  if (!isPlausibleQuad(analysisQuad, analysis.width, analysis.height)) return null;

  const xScale = source.width / analysis.width;
  const yScale = source.height / analysis.height;
  return {
    topLeft: scalePoint(analysisQuad.topLeft, xScale, yScale),
    topRight: scalePoint(analysisQuad.topRight, xScale, yScale),
    bottomRight: scalePoint(analysisQuad.bottomRight, xScale, yScale),
    bottomLeft: scalePoint(analysisQuad.bottomLeft, xScale, yScale),
  };
}

function fitVerticalBoundary(
  gray: Uint8Array,
  width: number,
  height: number,
  side: "left" | "right",
): FittedLine | null {
  const points: Array<Point & { weight: number }> = [];
  const minimum = side === "left" ? 2 : Math.round(width * 0.76);
  const maximum = side === "left" ? Math.round(width * 0.24) : width - 3;

  for (let y = Math.round(height * 0.08); y < height * 0.92; y += 2) {
    let bestX = minimum;
    let bestScore = 0;
    for (let x = minimum; x <= maximum; x += 1) {
      const offset = y * width + x;
      const score = Math.abs(gray[offset + 1] - gray[offset - 1])
        + Math.abs(gray[offset + width + 1] - gray[offset + width - 1]);
      if (score > bestScore) {
        bestScore = score;
        bestX = x;
      }
    }
    if (bestScore >= 34) points.push({ x: bestX, y, weight: bestScore });
  }

  return fitRobustLine(points, "y", "x", Math.max(4, width * 0.025));
}

function fitHorizontalBoundary(
  gray: Uint8Array,
  width: number,
  height: number,
  side: "top" | "bottom",
): FittedLine | null {
  const points: Array<Point & { weight: number }> = [];
  const minimum = side === "top" ? 2 : Math.round(height * 0.76);
  const maximum = side === "top" ? Math.round(height * 0.24) : height - 3;

  for (let x = Math.round(width * 0.08); x < width * 0.92; x += 2) {
    let bestY = minimum;
    let bestScore = 0;
    for (let y = minimum; y <= maximum; y += 1) {
      const offset = y * width + x;
      const score = Math.abs(gray[offset + width] - gray[offset - width])
        + Math.abs(gray[offset + width + 1] - gray[offset - width + 1]);
      if (score > bestScore) {
        bestScore = score;
        bestY = y;
      }
    }
    if (bestScore >= 34) points.push({ x, y: bestY, weight: bestScore });
  }

  return fitRobustLine(points, "x", "y", Math.max(4, height * 0.025));
}

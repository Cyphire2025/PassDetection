"use client";

import type { PassportPageSide } from "./passport-frame-detector";

/**
 * Shared passport-page normalization used by both the front and back scanner.
 * Camera captures are already constrained by the on-screen guide. This module
 * finds the four document edges inside that guide, rectifies the quadrilateral,
 * and crops away the small capture margin.
 */
export interface PassportNormalizationResult {
  file: File;
  corrected: boolean;
}

export type PassportCanvasNormalizationResult = PassportNormalizationResult;

interface Point {
  x: number;
  y: number;
}

interface DocumentQuad {
  topLeft: Point;
  topRight: Point;
  bottomRight: Point;
  bottomLeft: Point;
}

interface FittedLine {
  slope: number;
  intercept: number;
  support: number;
}

const ANALYSIS_MAX_WIDTH = 520;
const OUTPUT_MAX_DIMENSION = 1800;

export async function normalizePassportFile(
  file: File,
  pageSide: PassportPageSide = "front",
): Promise<PassportNormalizationResult> {
  if (!file.type.startsWith("image/")) {
    return { file, corrected: false };
  }

  let bitmap: ImageBitmap | null = null;
  try {
    bitmap = await createImageBitmap(file);
    if (bitmap.width < 640 || bitmap.height < 440) {
      return { file, corrected: false };
    }

    const source = document.createElement("canvas");
    source.width = bitmap.width;
    source.height = bitmap.height;
    const context = source.getContext("2d");
    if (!context) return { file, corrected: false };
    context.drawImage(bitmap, 0, 0);

    await nextAnimationFrame();
    const detectedQuad = detectDocumentQuad(source);
    if (!detectedQuad) return { file, corrected: false };
    const normalized = rectifyDocument(source, detectedQuad);
    if (
      normalized === source
      || !isSafeCorrectedPage(normalized, pageSide)
    ) {
      return { file, corrected: false };
    }

    return {
      file: await canvasToFile(normalized, file.name),
      corrected: true,
    };
  } catch {
    // File upload is an explicit fallback. If decoding or conservative
    // rectification is unavailable, preserve the original instead of
    // silently returning a damaged crop.
    return { file, corrected: false };
  } finally {
    bitmap?.close();
  }
}

export async function normalizePassportCanvasCapture(
  sourceCanvas: HTMLCanvasElement,
  fileName = "passport-capture.jpg",
  pageSide: PassportPageSide = "front",
): Promise<PassportCanvasNormalizationResult> {
  await nextAnimationFrame();
  const detectedQuad = detectDocumentQuad(sourceCanvas);
  const correctionCandidate = detectedQuad
    ? rectifyDocument(sourceCanvas, detectedQuad)
    : sourceCanvas;
  const corrected = correctionCandidate !== sourceCanvas
    && isSafeCorrectedPage(correctionCandidate, pageSide);
  const normalizedCanvas = corrected ? correctionCandidate : sourceCanvas;
  const file = await canvasToFile(normalizedCanvas, fileName);

  return {
    file,
    corrected,
  };
}

function detectDocumentQuad(source: HTMLCanvasElement): DocumentQuad | null {
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

function fitRobustLine(
  points: Array<Point & { weight: number }>,
  independent: "x" | "y",
  dependent: "x" | "y",
  maximumResidual: number,
): FittedLine | null {
  if (points.length < 18) return null;
  const initial = weightedLineFit(points, independent, dependent);
  if (!initial) return null;
  const inliers = points.filter((point) => (
    Math.abs(point[dependent] - ((initial.slope * point[independent]) + initial.intercept))
      <= maximumResidual
  ));
  if (inliers.length < Math.max(16, points.length * 0.38)) return null;
  const refined = weightedLineFit(inliers, independent, dependent);
  return refined ? { ...refined, support: inliers.length / points.length } : null;
}

function weightedLineFit(
  points: Array<Point & { weight: number }>,
  independent: "x" | "y",
  dependent: "x" | "y",
): Omit<FittedLine, "support"> | null {
  let totalWeight = 0;
  let independentMean = 0;
  let dependentMean = 0;
  for (const point of points) {
    totalWeight += point.weight;
    independentMean += point[independent] * point.weight;
    dependentMean += point[dependent] * point.weight;
  }
  if (totalWeight <= 0) return null;
  independentMean /= totalWeight;
  dependentMean /= totalWeight;

  let numerator = 0;
  let denominator = 0;
  for (const point of points) {
    const independentDelta = point[independent] - independentMean;
    numerator += point.weight * independentDelta * (point[dependent] - dependentMean);
    denominator += point.weight * independentDelta * independentDelta;
  }
  if (denominator < 0.001) return null;
  const slope = numerator / denominator;
  return { slope, intercept: dependentMean - (slope * independentMean) };
}

function intersectVerticalAndHorizontal(vertical: FittedLine, horizontal: FittedLine): Point {
  // vertical: x = slope * y + intercept
  // horizontal: y = slope * x + intercept
  const denominator = 1 - (vertical.slope * horizontal.slope);
  const x = Math.abs(denominator) < 0.0001
    ? vertical.intercept
    : ((vertical.slope * horizontal.intercept) + vertical.intercept) / denominator;
  return { x, y: (horizontal.slope * x) + horizontal.intercept };
}

function isPlausibleQuad(quad: DocumentQuad, width: number, height: number) {
  const points = [quad.topLeft, quad.topRight, quad.bottomRight, quad.bottomLeft];
  const withinBounds = points.every((point) => (
    point.x >= -width * 0.04
    && point.x <= width * 1.04
    && point.y >= -height * 0.04
    && point.y <= height * 1.04
  ));
  if (!withinBounds) return false;

  const topWidth = distance(quad.topLeft, quad.topRight);
  const bottomWidth = distance(quad.bottomLeft, quad.bottomRight);
  const leftHeight = distance(quad.topLeft, quad.bottomLeft);
  const rightHeight = distance(quad.topRight, quad.bottomRight);
  const averageWidth = (topWidth + bottomWidth) / 2;
  const averageHeight = (leftHeight + rightHeight) / 2;
  const aspectRatio = averageWidth / Math.max(1, averageHeight);
  const area = polygonArea(points);

  return area >= width * height * 0.48
    && aspectRatio >= 1.08
    && aspectRatio <= 1.85
    && Math.min(topWidth, bottomWidth) >= width * 0.58
    && Math.min(leftHeight, rightHeight) >= height * 0.58;
}

function rectifyDocument(source: HTMLCanvasElement, quad: DocumentQuad) {
  const measuredWidth = (
    distance(quad.topLeft, quad.topRight) + distance(quad.bottomLeft, quad.bottomRight)
  ) / 2;
  const measuredHeight = (
    distance(quad.topLeft, quad.bottomLeft) + distance(quad.topRight, quad.bottomRight)
  ) / 2;
  const outputScale = Math.min(1, OUTPUT_MAX_DIMENSION / Math.max(measuredWidth, measuredHeight));
  const outputWidth = Math.max(640, Math.round(measuredWidth * outputScale));
  const outputHeight = Math.max(440, Math.round(measuredHeight * outputScale));

  const output = document.createElement("canvas");
  output.width = outputWidth;
  output.height = outputHeight;
  const sourceContext = source.getContext("2d", { willReadFrequently: true });
  const outputContext = output.getContext("2d");
  if (!sourceContext || !outputContext) return source;

  const sourcePixels = sourceContext.getImageData(0, 0, source.width, source.height);
  const outputPixels = outputContext.createImageData(outputWidth, outputHeight);
  const homography = solveDestinationToSourceHomography(quad);
  if (!homography) return source;

  for (let y = 0; y < outputHeight; y += 1) {
    const normalizedY = y / Math.max(1, outputHeight - 1);
    for (let x = 0; x < outputWidth; x += 1) {
      const normalizedX = x / Math.max(1, outputWidth - 1);
      const denominator = (homography[6] * normalizedX) + (homography[7] * normalizedY) + 1;
      const sourceX = (
        (homography[0] * normalizedX) + (homography[1] * normalizedY) + homography[2]
      ) / denominator;
      const sourceY = (
        (homography[3] * normalizedX) + (homography[4] * normalizedY) + homography[5]
      ) / denominator;
      sampleBilinear(
        sourcePixels.data,
        source.width,
        source.height,
        outputPixels.data,
        (y * outputWidth + x) * 4,
        sourceX,
        sourceY,
      );
    }
  }

  outputContext.putImageData(outputPixels, 0, 0);
  return output;
}

function isSafeCorrectedPage(
  canvas: HTMLCanvasElement,
  pageSide: PassportPageSide,
) {
  if (canvas.width < 640 || canvas.height < 440) return false;
  const aspectRatio = canvas.width / Math.max(1, canvas.height);
  if (aspectRatio < 1.08 || aspectRatio > 1.85) return false;

  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return false;
  const sampleWidth = Math.min(320, canvas.width);
  const sampleHeight = Math.max(
    1,
    Math.round(sampleWidth / aspectRatio),
  );
  const sample = document.createElement("canvas");
  sample.width = sampleWidth;
  sample.height = sampleHeight;
  const sampleContext = sample.getContext("2d", { willReadFrequently: true });
  if (!sampleContext) return false;
  sampleContext.drawImage(canvas, 0, 0, sampleWidth, sampleHeight);
  const pixels = sampleContext.getImageData(
    0,
    0,
    sampleWidth,
    sampleHeight,
  ).data;
  return isGenericCorrectionContentSafe(
    pixels,
    sampleWidth,
    sampleHeight,
    pageSide,
  );
}

function isGenericCorrectionContentSafe(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
  pageSide: PassportPageSide,
): boolean {
  const gray = toGrayscale(pixels, width, height);
  const overall = genericRegionQuality(gray, width, height, {
    left: 0.03,
    top: 0.04,
    right: 0.97,
    bottom: 0.96,
  });
  if (overall.contrast < 9 || overall.detailDensity < 0.007) return false;

  const regions = pageSide === "front"
    ? [
        { left: 0.34, top: 0.08, right: 0.97, bottom: 0.70 },
        { left: 0.04, top: 0.66, right: 0.97, bottom: 0.96 },
        { left: 0.03, top: 0.08, right: 0.38, bottom: 0.70 },
      ]
    : [
        { left: 0.10, top: 0.12, right: 0.90, bottom: 0.66 },
        { left: 0.08, top: 0.55, right: 0.92, bottom: 0.92 },
      ];
  const usefulRegions = regions.filter((region) => {
    const quality = genericRegionQuality(gray, width, height, region);
    return quality.contrast >= 7.5 && quality.detailDensity >= 0.006;
  }).length;
  return usefulRegions >= (pageSide === "front" ? 2 : 1);
}

function genericRegionQuality(
  gray: Uint8Array,
  width: number,
  height: number,
  region: {
    left: number;
    top: number;
    right: number;
    bottom: number;
  },
) {
  const left = Math.max(1, Math.round(region.left * (width - 1)));
  const right = Math.min(
    width - 2,
    Math.round(region.right * (width - 1)),
  );
  const top = Math.max(1, Math.round(region.top * (height - 1)));
  const bottom = Math.min(
    height - 2,
    Math.round(region.bottom * (height - 1)),
  );
  let samples = 0;
  let total = 0;
  let squaredTotal = 0;
  let detailed = 0;
  for (let y = top; y <= bottom; y += 1) {
    for (let x = left; x <= right; x += 1) {
      const index = y * width + x;
      const luminance = gray[index];
      samples += 1;
      total += luminance;
      squaredTotal += luminance * luminance;
      if (
        Math.abs(gray[index + 1] - gray[index - 1])
          + Math.abs(gray[index + width] - gray[index - width])
        >= 28
      ) {
        detailed += 1;
      }
    }
  }
  const mean = total / Math.max(1, samples);
  return {
    contrast: Math.sqrt(Math.max(
      0,
      squaredTotal / Math.max(1, samples) - mean * mean,
    )),
    detailDensity: detailed / Math.max(1, samples),
  };
}

function solveDestinationToSourceHomography(quad: DocumentQuad): number[] | null {
  const destinations: Point[] = [
    { x: 0, y: 0 },
    { x: 1, y: 0 },
    { x: 1, y: 1 },
    { x: 0, y: 1 },
  ];
  const sources = [quad.topLeft, quad.topRight, quad.bottomRight, quad.bottomLeft];
  const matrix: number[][] = [];

  for (let index = 0; index < destinations.length; index += 1) {
    const { x: u, y: v } = destinations[index];
    const { x, y } = sources[index];
    matrix.push([u, v, 1, 0, 0, 0, -u * x, -v * x, x]);
    matrix.push([0, 0, 0, u, v, 1, -u * y, -v * y, y]);
  }

  return solveAugmentedMatrix(matrix);
}

function solveAugmentedMatrix(matrix: number[][]): number[] | null {
  const size = matrix.length;
  for (let column = 0; column < size; column += 1) {
    let pivot = column;
    for (let row = column + 1; row < size; row += 1) {
      if (Math.abs(matrix[row][column]) > Math.abs(matrix[pivot][column])) pivot = row;
    }
    if (Math.abs(matrix[pivot][column]) < 1e-9) return null;
    [matrix[column], matrix[pivot]] = [matrix[pivot], matrix[column]];

    const divisor = matrix[column][column];
    for (let item = column; item <= size; item += 1) matrix[column][item] /= divisor;
    for (let row = 0; row < size; row += 1) {
      if (row === column) continue;
      const factor = matrix[row][column];
      for (let item = column; item <= size; item += 1) {
        matrix[row][item] -= factor * matrix[column][item];
      }
    }
  }
  return matrix.map((row) => row[size]);
}

function sampleBilinear(
  source: Uint8ClampedArray,
  width: number,
  height: number,
  destination: Uint8ClampedArray,
  destinationOffset: number,
  x: number,
  y: number,
) {
  const clampedX = Math.max(0, Math.min(width - 1, x));
  const clampedY = Math.max(0, Math.min(height - 1, y));
  const x0 = Math.floor(clampedX);
  const y0 = Math.floor(clampedY);
  const x1 = Math.min(width - 1, x0 + 1);
  const y1 = Math.min(height - 1, y0 + 1);
  const xWeight = clampedX - x0;
  const yWeight = clampedY - y0;
  const offsets = [
    (y0 * width + x0) * 4,
    (y0 * width + x1) * 4,
    (y1 * width + x0) * 4,
    (y1 * width + x1) * 4,
  ];

  for (let channel = 0; channel < 4; channel += 1) {
    const top = source[offsets[0] + channel] * (1 - xWeight)
      + source[offsets[1] + channel] * xWeight;
    const bottom = source[offsets[2] + channel] * (1 - xWeight)
      + source[offsets[3] + channel] * xWeight;
    destination[destinationOffset + channel] = Math.round(
      top * (1 - yWeight) + bottom * yWeight,
    );
  }
}

function toGrayscale(data: Uint8ClampedArray, width: number, height: number) {
  const gray = new Uint8Array(width * height);
  for (let pixel = 0, offset = 0; pixel < gray.length; pixel += 1, offset += 4) {
    gray[pixel] = Math.round(
      (data[offset] * 0.299) + (data[offset + 1] * 0.587) + (data[offset + 2] * 0.114),
    );
  }
  return gray;
}

function distance(first: Point, second: Point) {
  return Math.hypot(second.x - first.x, second.y - first.y);
}

function polygonArea(points: Point[]) {
  let area = 0;
  for (let index = 0; index < points.length; index += 1) {
    const next = points[(index + 1) % points.length];
    area += (points[index].x * next.y) - (next.x * points[index].y);
  }
  return Math.abs(area) / 2;
}

function scalePoint(point: Point, xScale: number, yScale: number): Point {
  return { x: point.x * xScale, y: point.y * yScale };
}

async function canvasToFile(canvas: HTMLCanvasElement, fileName: string): Promise<File> {
  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((createdBlob) => {
      if (!createdBlob) {
        reject(new Error("Failed to create passport image"));
        return;
      }
      resolve(createdBlob);
    }, "image/jpeg", 0.95);
  });

  return new File([blob], fileName.replace(/\.[^.]+$/, "") + ".jpg", {
    type: "image/jpeg",
    lastModified: Date.now(),
  });
}

function nextAnimationFrame() {
  return new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
}

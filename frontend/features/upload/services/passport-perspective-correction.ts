"use client";

interface Point {
  x: number;
  y: number;
}

interface HorizontalLine {
  m: number;
  b: number;
}

interface VerticalLine {
  m: number;
  b: number;
}

interface PassportQuadrilateral {
  topLeft: Point;
  topRight: Point;
  bottomRight: Point;
  bottomLeft: Point;
}

export interface PassportNormalizationResult {
  file: File;
  previewDataUrl: string;
  corrected: boolean;
}

const PASSPORT_ASPECT_RATIO = 1.42;
const MAX_SOURCE_DIMENSION = 2000;
const MAX_OUTPUT_WIDTH = 1600;
const SAMPLE_LONG_EDGE = 720;
const MIN_EDGE_THRESHOLD = 24;

export async function normalizePassportFile(file: File): Promise<PassportNormalizationResult> {
  const sourceCanvas = await renderFileToCanvas(file);
  const correctedCanvas = correctPerspectiveIfPossible(sourceCanvas) ?? sourceCanvas;

  return {
    file: await canvasToFile(correctedCanvas, file.name || "passport-upload.jpg"),
    previewDataUrl: correctedCanvas.toDataURL("image/jpeg", 0.92),
    corrected: correctedCanvas !== sourceCanvas,
  };
}

export async function normalizePassportCanvasCapture(
  sourceCanvas: HTMLCanvasElement,
  fileName = "passport-capture.jpg",
): Promise<PassportNormalizationResult> {
  const correctedCanvas = correctPerspectiveIfPossible(sourceCanvas) ?? sourceCanvas;

  return {
    file: await canvasToFile(correctedCanvas, fileName),
    previewDataUrl: correctedCanvas.toDataURL("image/jpeg", 0.92),
    corrected: correctedCanvas !== sourceCanvas,
  };
}

function correctPerspectiveIfPossible(sourceCanvas: HTMLCanvasElement): HTMLCanvasElement | null {
  const quadrilateral = detectPassportQuadrilateral(sourceCanvas);
  if (!quadrilateral) {
    return null;
  }

  return warpPassportQuadrilateral(sourceCanvas, quadrilateral);
}

async function renderFileToCanvas(file: File): Promise<HTMLCanvasElement> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, MAX_SOURCE_DIMENSION / Math.max(bitmap.width, bitmap.height));
  const width = Math.max(1, Math.round(bitmap.width * scale));
  const height = Math.max(1, Math.round(bitmap.height * scale));

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;

  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("Failed to create canvas context for passport normalization");
  }

  context.drawImage(bitmap, 0, 0, width, height);
  bitmap.close();
  return canvas;
}

function detectPassportQuadrilateral(sourceCanvas: HTMLCanvasElement): PassportQuadrilateral | null {
  const sampleCanvas = createSampleCanvas(sourceCanvas);
  const context = sampleCanvas.getContext("2d", { willReadFrequently: true });
  if (!context) return null;

  const width = sampleCanvas.width;
  const height = sampleCanvas.height;
  const { data } = context.getImageData(0, 0, width, height);
  const gray = new Uint8Array(width * height);

  for (let pixel = 0, offset = 0; pixel < gray.length; pixel += 1, offset += 4) {
    gray[pixel] = Math.round(data[offset] * 0.299 + data[offset + 1] * 0.587 + data[offset + 2] * 0.114);
  }

  const edgeThreshold = computeAdaptiveEdgeThreshold(gray, width, height);
  const topPoints = scanHorizontalBoundary(gray, width, height, edgeThreshold, "top");
  const bottomPoints = scanHorizontalBoundary(gray, width, height, edgeThreshold, "bottom");
  const leftPoints = scanVerticalBoundary(gray, width, height, edgeThreshold, "left");
  const rightPoints = scanVerticalBoundary(gray, width, height, edgeThreshold, "right");

  const topLine = fitHorizontalLine(topPoints);
  const bottomLine = fitHorizontalLine(bottomPoints);
  const leftLine = fitVerticalLine(leftPoints);
  const rightLine = fitVerticalLine(rightPoints);

  if (!topLine || !bottomLine || !leftLine || !rightLine) {
    return null;
  }

  const sampleQuadrilateral = {
    topLeft: intersectLines(topLine, leftLine),
    topRight: intersectLines(topLine, rightLine),
    bottomRight: intersectLines(bottomLine, rightLine),
    bottomLeft: intersectLines(bottomLine, leftLine),
  };

  if (!isValidQuadrilateral(sampleQuadrilateral, width, height)) {
    return null;
  }

  const scaleX = sourceCanvas.width / width;
  const scaleY = sourceCanvas.height / height;

  return {
    topLeft: scalePoint(sampleQuadrilateral.topLeft, scaleX, scaleY),
    topRight: scalePoint(sampleQuadrilateral.topRight, scaleX, scaleY),
    bottomRight: scalePoint(sampleQuadrilateral.bottomRight, scaleX, scaleY),
    bottomLeft: scalePoint(sampleQuadrilateral.bottomLeft, scaleX, scaleY),
  };
}

function createSampleCanvas(sourceCanvas: HTMLCanvasElement): HTMLCanvasElement {
  const scale = Math.min(1, SAMPLE_LONG_EDGE / Math.max(sourceCanvas.width, sourceCanvas.height));
  const width = Math.max(1, Math.round(sourceCanvas.width * scale));
  const height = Math.max(1, Math.round(sourceCanvas.height * scale));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;

  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("Failed to create sample canvas");
  }

  context.drawImage(sourceCanvas, 0, 0, width, height);
  return canvas;
}

function computeAdaptiveEdgeThreshold(gray: Uint8Array, width: number, height: number): number {
  let total = 0;
  let samples = 0;

  for (let y = 2; y < height - 2; y += 8) {
    for (let x = 2; x < width - 2; x += 8) {
      const index = y * width + x;
      const horizontal = Math.abs(gray[index + 1] - gray[index - 1]);
      const vertical = Math.abs(gray[index + width] - gray[index - width]);
      total += Math.max(horizontal, vertical);
      samples += 1;
    }
  }

  const average = samples > 0 ? total / samples : MIN_EDGE_THRESHOLD;
  return Math.max(MIN_EDGE_THRESHOLD, average * 2.2);
}

function scanHorizontalBoundary(
  gray: Uint8Array,
  width: number,
  height: number,
  threshold: number,
  side: "top" | "bottom",
): Point[] {
  const points: Point[] = [];
  const marginX = Math.round(width * 0.08);
  const startY = side === "top" ? 6 : height - 7;
  const endY = side === "top" ? Math.floor(height * 0.58) : Math.ceil(height * 0.42);
  const direction = side === "top" ? 1 : -1;

  for (let x = marginX; x < width - marginX; x += 8) {
    let bestY = -1;
    let bestScore = 0;

    for (let y = startY; side === "top" ? y < endY : y > endY; y += direction) {
      const index = y * width + x;
      const score =
        Math.abs(gray[index + width] - gray[index - width]) * 0.7 +
        Math.abs(gray[index + 2 * width] - gray[index - 2 * width]) * 0.3;

      if (score > threshold && score > bestScore) {
        bestScore = score;
        bestY = y;
        break;
      }
    }

    if (bestY > 0) {
      points.push({ x, y: bestY });
    }
  }

  return points;
}

function scanVerticalBoundary(
  gray: Uint8Array,
  width: number,
  height: number,
  threshold: number,
  side: "left" | "right",
): Point[] {
  const points: Point[] = [];
  const marginY = Math.round(height * 0.1);
  const startX = side === "left" ? 6 : width - 7;
  const endX = side === "left" ? Math.floor(width * 0.48) : Math.ceil(width * 0.52);
  const direction = side === "left" ? 1 : -1;

  for (let y = marginY; y < height - marginY; y += 8) {
    let bestX = -1;
    let bestScore = 0;

    for (let x = startX; side === "left" ? x < endX : x > endX; x += direction) {
      const index = y * width + x;
      const score =
        Math.abs(gray[index + 1] - gray[index - 1]) * 0.7 +
        Math.abs(gray[index + 2] - gray[index - 2]) * 0.3;

      if (score > threshold && score > bestScore) {
        bestScore = score;
        bestX = x;
        break;
      }
    }

    if (bestX > 0) {
      points.push({ x: bestX, y });
    }
  }

  return points;
}

function fitHorizontalLine(points: Point[]): HorizontalLine | null {
  if (points.length < 8) return null;
  const initial = linearRegression(points, "x", "y");
  const refined = rejectOutliers(points, initial, "horizontal");
  return refined.length >= 8 ? linearRegression(refined, "x", "y") : initial;
}

function fitVerticalLine(points: Point[]): VerticalLine | null {
  if (points.length < 8) return null;
  const initial = linearRegression(points, "y", "x");
  const refined = rejectOutliers(points, initial, "vertical");
  return refined.length >= 8 ? linearRegression(refined, "y", "x") : initial;
}

function linearRegression(
  points: Point[],
  predictorAxis: "x" | "y",
  responseAxis: "x" | "y",
): { m: number; b: number } {
  let predictorTotal = 0;
  let responseTotal = 0;

  for (const point of points) {
    predictorTotal += point[predictorAxis];
    responseTotal += point[responseAxis];
  }

  const predictorMean = predictorTotal / points.length;
  const responseMean = responseTotal / points.length;

  let covariance = 0;
  let variance = 0;
  for (const point of points) {
    const predictor = point[predictorAxis] - predictorMean;
    covariance += predictor * (point[responseAxis] - responseMean);
    variance += predictor * predictor;
  }

  const m = variance === 0 ? 0 : covariance / variance;
  const b = responseMean - m * predictorMean;
  return { m, b };
}

function rejectOutliers(
  points: Point[],
  line: { m: number; b: number },
  orientation: "horizontal" | "vertical",
): Point[] {
  const residuals = points
    .map((point) => ({
      point,
      residual: Math.abs(
        orientation === "horizontal"
          ? point.y - (line.m * point.x + line.b)
          : point.x - (line.m * point.y + line.b),
      ),
    }))
    .sort((a, b) => a.residual - b.residual);

  const cutoffIndex = Math.max(0, Math.floor(residuals.length * 0.8) - 1);
  const cutoff = Math.max(10, residuals[cutoffIndex]?.residual ?? 10);
  return residuals.filter((entry) => entry.residual <= cutoff).map((entry) => entry.point);
}

function intersectLines(horizontal: HorizontalLine, vertical: VerticalLine): Point {
  const denominator = 1 - vertical.m * horizontal.m;
  const x = denominator === 0 ? 0 : (vertical.m * horizontal.b + vertical.b) / denominator;
  const y = horizontal.m * x + horizontal.b;
  return { x, y };
}

function isValidQuadrilateral(
  quadrilateral: PassportQuadrilateral,
  width: number,
  height: number,
): boolean {
  const corners = [
    quadrilateral.topLeft,
    quadrilateral.topRight,
    quadrilateral.bottomRight,
    quadrilateral.bottomLeft,
  ];

  if (corners.some((point) => point.x < -8 || point.x > width + 8 || point.y < -8 || point.y > height + 8)) {
    return false;
  }

  const topWidth = distance(quadrilateral.topLeft, quadrilateral.topRight);
  const bottomWidth = distance(quadrilateral.bottomLeft, quadrilateral.bottomRight);
  const leftHeight = distance(quadrilateral.topLeft, quadrilateral.bottomLeft);
  const rightHeight = distance(quadrilateral.topRight, quadrilateral.bottomRight);
  const averageWidth = (topWidth + bottomWidth) / 2;
  const averageHeight = (leftHeight + rightHeight) / 2;

  if (averageWidth < width * 0.48 || averageHeight < height * 0.38) {
    return false;
  }

  const ratio = averageWidth / Math.max(averageHeight, 1);
  if (ratio < 1.2 || ratio > 1.7) {
    return false;
  }

  const area = polygonArea(corners);
  return area >= width * height * 0.22;
}

function warpPassportQuadrilateral(
  sourceCanvas: HTMLCanvasElement,
  quadrilateral: PassportQuadrilateral,
): HTMLCanvasElement | null {
  const topWidth = distance(quadrilateral.topLeft, quadrilateral.topRight);
  const bottomWidth = distance(quadrilateral.bottomLeft, quadrilateral.bottomRight);
  const leftHeight = distance(quadrilateral.topLeft, quadrilateral.bottomLeft);
  const rightHeight = distance(quadrilateral.topRight, quadrilateral.bottomRight);

  const averageWidth = (topWidth + bottomWidth) / 2;
  const averageHeight = (leftHeight + rightHeight) / 2;

  const widthByHeight = averageHeight * PASSPORT_ASPECT_RATIO;
  const blendedWidth = Math.min(averageWidth, widthByHeight * 1.08);
  const outputWidth = Math.max(640, Math.min(MAX_OUTPUT_WIDTH, Math.round(blendedWidth)));
  const outputHeight = Math.max(450, Math.round(outputWidth / PASSPORT_ASPECT_RATIO));

  const transform = solvePerspectiveTransform(
    [
      { x: 0, y: 0 },
      { x: outputWidth - 1, y: 0 },
      { x: outputWidth - 1, y: outputHeight - 1 },
      { x: 0, y: outputHeight - 1 },
    ],
    [
      quadrilateral.topLeft,
      quadrilateral.topRight,
      quadrilateral.bottomRight,
      quadrilateral.bottomLeft,
    ],
  );

  if (!transform) {
    return null;
  }

  const sourceContext = sourceCanvas.getContext("2d", { willReadFrequently: true });
  if (!sourceContext) {
    return null;
  }

  const sourceImage = sourceContext.getImageData(0, 0, sourceCanvas.width, sourceCanvas.height);
  const outputCanvas = document.createElement("canvas");
  outputCanvas.width = outputWidth;
  outputCanvas.height = outputHeight;
  const outputContext = outputCanvas.getContext("2d");
  if (!outputContext) {
    return null;
  }

  const outputImage = outputContext.createImageData(outputWidth, outputHeight);
  const destination = outputImage.data;
  const source = sourceImage.data;

  for (let y = 0; y < outputHeight; y += 1) {
    for (let x = 0; x < outputWidth; x += 1) {
      const sourcePoint = applyPerspectiveTransform(transform, x, y);
      const pixel = sampleBilinear(source, sourceCanvas.width, sourceCanvas.height, sourcePoint.x, sourcePoint.y);
      const offset = (y * outputWidth + x) * 4;
      destination[offset] = pixel[0];
      destination[offset + 1] = pixel[1];
      destination[offset + 2] = pixel[2];
      destination[offset + 3] = pixel[3];
    }
  }

  outputContext.putImageData(outputImage, 0, 0);
  return outputCanvas;
}

function solvePerspectiveTransform(destination: Point[], source: Point[]): number[] | null {
  const matrix: number[][] = [];
  const values: number[] = [];

  for (let index = 0; index < 4; index += 1) {
    const { x: u, y: v } = destination[index];
    const { x, y } = source[index];

    matrix.push([u, v, 1, 0, 0, 0, -u * x, -v * x]);
    values.push(x);
    matrix.push([0, 0, 0, u, v, 1, -u * y, -v * y]);
    values.push(y);
  }

  return solveLinearSystem(matrix, values);
}

function solveLinearSystem(matrix: number[][], values: number[]): number[] | null {
  const size = values.length;
  const augmented = matrix.map((row, index) => [...row, values[index]]);

  for (let pivot = 0; pivot < size; pivot += 1) {
    let maxRow = pivot;
    for (let row = pivot + 1; row < size; row += 1) {
      if (Math.abs(augmented[row][pivot]) > Math.abs(augmented[maxRow][pivot])) {
        maxRow = row;
      }
    }

    if (Math.abs(augmented[maxRow][pivot]) < 1e-8) {
      return null;
    }

    [augmented[pivot], augmented[maxRow]] = [augmented[maxRow], augmented[pivot]];
    const pivotValue = augmented[pivot][pivot];

    for (let column = pivot; column <= size; column += 1) {
      augmented[pivot][column] /= pivotValue;
    }

    for (let row = 0; row < size; row += 1) {
      if (row === pivot) continue;
      const factor = augmented[row][pivot];
      for (let column = pivot; column <= size; column += 1) {
        augmented[row][column] -= factor * augmented[pivot][column];
      }
    }
  }

  return augmented.map((row) => row[size]);
}

function applyPerspectiveTransform(transform: number[], x: number, y: number): Point {
  const [a, b, c, d, e, f, g, h] = transform;
  const denominator = g * x + h * y + 1;
  return {
    x: (a * x + b * y + c) / denominator,
    y: (d * x + e * y + f) / denominator,
  };
}

function sampleBilinear(
  data: Uint8ClampedArray,
  width: number,
  height: number,
  x: number,
  y: number,
): [number, number, number, number] {
  const clampedX = Math.min(width - 1, Math.max(0, x));
  const clampedY = Math.min(height - 1, Math.max(0, y));

  const left = Math.floor(clampedX);
  const top = Math.floor(clampedY);
  const right = Math.min(width - 1, left + 1);
  const bottom = Math.min(height - 1, top + 1);
  const xWeight = clampedX - left;
  const yWeight = clampedY - top;

  const topLeft = getPixel(data, width, left, top);
  const topRight = getPixel(data, width, right, top);
  const bottomLeft = getPixel(data, width, left, bottom);
  const bottomRight = getPixel(data, width, right, bottom);

  return [0, 1, 2, 3].map((channel) => {
    const topMix = topLeft[channel] * (1 - xWeight) + topRight[channel] * xWeight;
    const bottomMix = bottomLeft[channel] * (1 - xWeight) + bottomRight[channel] * xWeight;
    return Math.round(topMix * (1 - yWeight) + bottomMix * yWeight);
  }) as [number, number, number, number];
}

function getPixel(data: Uint8ClampedArray, width: number, x: number, y: number): [number, number, number, number] {
  const offset = (y * width + x) * 4;
  return [data[offset], data[offset + 1], data[offset + 2], data[offset + 3]];
}

function scalePoint(point: Point, scaleX: number, scaleY: number): Point {
  return {
    x: point.x * scaleX,
    y: point.y * scaleY,
  };
}

function distance(a: Point, b: Point): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function polygonArea(points: Point[]): number {
  let area = 0;
  for (let index = 0; index < points.length; index += 1) {
    const current = points[index];
    const next = points[(index + 1) % points.length];
    area += current.x * next.y - next.x * current.y;
  }
  return Math.abs(area / 2);
}

async function canvasToFile(canvas: HTMLCanvasElement, fileName: string): Promise<File> {
  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((createdBlob) => {
      if (!createdBlob) {
        reject(new Error("Failed to create upload image blob"));
        return;
      }

      resolve(createdBlob);
    }, "image/jpeg", 0.92);
  });

  return new File([blob], fileName.replace(/\.[^.]+$/, "") + ".jpg", { type: "image/jpeg" });
}

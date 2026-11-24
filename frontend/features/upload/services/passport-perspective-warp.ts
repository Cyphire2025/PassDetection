import type { DocumentQuad } from "./passport-normalization.types.ts";
import { distance } from "./passport-quad-geometry.ts";
import { solveDestinationToSourceHomography } from "./passport-homography.ts";

const OUTPUT_MAX_DIMENSION = 1800;

export function rectifyDocument(source: HTMLCanvasElement, quad: DocumentQuad) {
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

import type { Point, DocumentQuad } from "./passport-live.types.ts";
import { PASSPORT_LIVE_THRESHOLDS } from "./passport-live-policy.ts";

/**
 * Looks only for useful visual detail distributed through the page interior.
 * It does not recognize text, fields, faces, or MRZ structure. Requiring
 * several low-resolution tiles across more than one row prevents a blank
 * booklet page with a narrow strip of the real information page from passing.
 */
export function analyzeInteriorDetail(
  gray: Uint8Array,
  width: number,
  height: number,
  quad: DocumentQuad,
) {
  const columns = PASSPORT_LIVE_THRESHOLDS.detailColumns;
  const rows = PASSPORT_LIVE_THRESHOLDS.detailRows;
  const detailedByRow = new Uint8Array(rows);
  let detailedTiles = 0;

  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      const tile = sampleInteriorTile(
        gray,
        width,
        height,
        quad,
        column,
        row,
        columns,
        rows,
      );
      if (
        tile.edgeRatio
          < PASSPORT_LIVE_THRESHOLDS.minimumDetailEdgeRatio
        || tile.deviation
          < PASSPORT_LIVE_THRESHOLDS.minimumDetailDeviation
      ) {
        continue;
      }
      detailedTiles += 1;
      detailedByRow[row] = 1;
    }
  }
  const detailedRows = detailedByRow.reduce(
    (sum, detailed) => sum + detailed,
    0,
  );
  return {
    tileRatio: detailedTiles / Math.max(1, columns * rows),
    rowCoverage: detailedRows / Math.max(1, rows),
  };
}

function sampleInteriorTile(
  gray: Uint8Array,
  width: number,
  height: number,
  quad: DocumentQuad,
  column: number,
  row: number,
  columns: number,
  rows: number,
) {
  // Stay well inside the fitted quadrilateral so page/background transitions
  // or an open-book crease cannot masquerade as distributed printed detail.
  const insetStart = 0.14;
  const insetSpan = 0.72;
  const samplesAcross = 18;
  const samplesDown = 14;
  let total = 0;
  let squaredTotal = 0;
  let edgeSamples = 0;
  let samples = 0;

  for (let sampleY = 0; sampleY < samplesDown; sampleY += 1) {
    const v = insetStart + insetSpan * (
      (row + (sampleY + 0.5) / samplesDown) / rows
    );
    for (let sampleX = 0; sampleX < samplesAcross; sampleX += 1) {
      const u = insetStart + insetSpan * (
        (column + (sampleX + 0.5) / samplesAcross) / columns
      );
      const point = pointInsideQuad(quad, u, v);
      const x = Math.max(1, Math.min(width - 2, Math.round(point.x)));
      const y = Math.max(1, Math.min(height - 2, Math.round(point.y)));
      const offset = y * width + x;
      const value = gray[offset];
      const gradient = (
        Math.abs(gray[offset + 1] - gray[offset - 1])
        + Math.abs(gray[offset + width] - gray[offset - width])
      );
      total += value;
      squaredTotal += value * value;
      if (gradient >= PASSPORT_LIVE_THRESHOLDS.detailGradient) {
        edgeSamples += 1;
      }
      samples += 1;
    }
  }
  const mean = total / Math.max(1, samples);
  return {
    edgeRatio: edgeSamples / Math.max(1, samples),
    deviation: Math.sqrt(
      Math.max(0, squaredTotal / Math.max(1, samples) - mean * mean),
    ),
  };
}

function pointInsideQuad(
  quad: DocumentQuad,
  u: number,
  v: number,
): Point {
  const top = {
    x: quad.topLeft.x * (1 - u) + quad.topRight.x * u,
    y: quad.topLeft.y * (1 - u) + quad.topRight.y * u,
  };
  const bottom = {
    x: quad.bottomLeft.x * (1 - u) + quad.bottomRight.x * u,
    y: quad.bottomLeft.y * (1 - u) + quad.bottomRight.y * u,
  };
  return {
    x: top.x * (1 - v) + bottom.x * v,
    y: top.y * (1 - v) + bottom.y * v,
  };
}

import type { Point, DocumentQuad, FittedLine } from "./passport-normalization.types.ts";

export function intersectVerticalAndHorizontal(vertical: FittedLine, horizontal: FittedLine): Point {
  // vertical: x = slope * y + intercept
  // horizontal: y = slope * x + intercept
  const denominator = 1 - (vertical.slope * horizontal.slope);
  const x = Math.abs(denominator) < 0.0001
    ? vertical.intercept
    : ((vertical.slope * horizontal.intercept) + vertical.intercept) / denominator;
  return { x, y: (horizontal.slope * x) + horizontal.intercept };
}

export function isPlausibleQuad(quad: DocumentQuad, width: number, height: number) {
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

export function distance(first: Point, second: Point) {
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

export function scalePoint(point: Point, xScale: number, yScale: number): Point {
  return { x: point.x * xScale, y: point.y * yScale };
}

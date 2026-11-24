import type { Point, BoundaryEvidence, DocumentQuad } from "./passport-live.types.ts";
import { PASSPORT_LIVE_THRESHOLDS } from "./passport-live-policy.ts";

export function createDocumentQuad(
  left: BoundaryEvidence,
  right: BoundaryEvidence,
  top: BoundaryEvidence,
  bottom: BoundaryEvidence,
): DocumentQuad {
  return {
    topLeft: intersectBoundaries(left, top),
    topRight: intersectBoundaries(right, top),
    bottomRight: intersectBoundaries(right, bottom),
    bottomLeft: intersectBoundaries(left, bottom),
  };
}

function intersectBoundaries(
  vertical: BoundaryEvidence,
  horizontal: BoundaryEvidence,
): Point {
  const denominator = 1 - vertical.slope * horizontal.slope;
  const x = Math.abs(denominator) < 0.0001
    ? vertical.intercept
    : (
        vertical.slope * horizontal.intercept
        + vertical.intercept
      ) / denominator;
  return {
    x,
    y: horizontal.slope * x + horizontal.intercept,
  };
}

export function measureDocumentGeometry(
  quad: DocumentQuad,
  left: BoundaryEvidence,
  right: BoundaryEvidence,
  top: BoundaryEvidence,
  bottom: BoundaryEvidence,
  width: number,
  height: number,
) {
  const points = [
    quad.topLeft,
    quad.topRight,
    quad.bottomRight,
    quad.bottomLeft,
  ];
  if (
    !points.every(
      (point) => Number.isFinite(point.x) && Number.isFinite(point.y),
    )
  ) {
    return {
      areaRatio: 0,
      skewDegrees: 0,
      hasExcessiveSkew: false,
      isGuideAligned: false,
    };
  }
  const topSpan = distance(quad.topLeft, quad.topRight);
  const bottomSpan = distance(quad.bottomLeft, quad.bottomRight);
  const leftSpan = distance(quad.topLeft, quad.bottomLeft);
  const rightSpan = distance(quad.topRight, quad.bottomRight);
  const horizontalSpanRatio = (
    (topSpan + bottomSpan) / 2
  ) / Math.max(1, width);
  const verticalSpanRatio = (
    (leftSpan + rightSpan) / 2
  ) / Math.max(1, height);
  const areaRatio = polygonArea(points) / Math.max(1, width * height);
  const centerX = points.reduce((sum, point) => sum + point.x, 0) / 4;
  const centerY = points.reduce((sum, point) => sum + point.y, 0) / 4;
  const leftAngle = radiansToDegrees(Math.atan(-left.slope));
  const rightAngle = radiansToDegrees(Math.atan(-right.slope));
  const topAngle = radiansToDegrees(Math.atan(top.slope));
  const bottomAngle = radiansToDegrees(Math.atan(bottom.slope));
  const verticalAngle = (leftAngle + rightAngle) / 2;
  const horizontalAngle = (topAngle + bottomAngle) / 2;
  const skewDegrees = Math.abs(
    (verticalAngle + horizontalAngle) / 2,
  );
  const oppositeVerticalDelta = Math.abs(leftAngle - rightAngle);
  const oppositeHorizontalDelta = Math.abs(topAngle - bottomAngle);
  const axisAngleDelta = Math.abs(verticalAngle - horizontalAngle);
  const hasExcessiveSkew = (
    skewDegrees > PASSPORT_LIVE_THRESHOLDS.maximumReadySkewDegrees
    || oppositeVerticalDelta
      > PASSPORT_LIVE_THRESHOLDS.maximumOppositeEdgeAngleDelta
    || oppositeHorizontalDelta
      > PASSPORT_LIVE_THRESHOLDS.maximumOppositeEdgeAngleDelta
    || axisAngleDelta
      > PASSPORT_LIVE_THRESHOLDS.maximumAxisAngleDelta
  );
  const spansFitGuide = (
    horizontalSpanRatio
      >= PASSPORT_LIVE_THRESHOLDS.minimumDocumentSpanRatio
    && horizontalSpanRatio
      <= PASSPORT_LIVE_THRESHOLDS.maximumDocumentSpanRatio
    && verticalSpanRatio
      >= PASSPORT_LIVE_THRESHOLDS.minimumDocumentSpanRatio
    && verticalSpanRatio
      <= PASSPORT_LIVE_THRESHOLDS.maximumDocumentSpanRatio
  );
  const centerFitsGuide = (
    Math.abs(centerX / width - 0.5)
      <= PASSPORT_LIVE_THRESHOLDS.maximumCenterOffsetRatio
    && Math.abs(centerY / height - 0.5)
      <= PASSPORT_LIVE_THRESHOLDS.maximumCenterOffsetRatio
  );
  const areaFitsGuide = (
    areaRatio >= PASSPORT_LIVE_THRESHOLDS.minimumDocumentAreaRatio
    && areaRatio <= PASSPORT_LIVE_THRESHOLDS.maximumDocumentAreaRatio
  );
  const oppositeSpansAgree = (
    Math.min(topSpan, bottomSpan) / Math.max(1, Math.max(topSpan, bottomSpan))
      >= 0.78
    && Math.min(leftSpan, rightSpan) / Math.max(1, Math.max(leftSpan, rightSpan))
      >= 0.78
  );

  return {
    areaRatio,
    skewDegrees,
    hasExcessiveSkew,
    isGuideAligned: (
      !hasExcessiveSkew
      && spansFitGuide
      && centerFitsGuide
      && areaFitsGuide
      && oppositeSpansAgree
      && isConvexQuad(quad)
    ),
  };
}

function isConvexQuad(quad: DocumentQuad): boolean {
  const points = [
    quad.topLeft,
    quad.topRight,
    quad.bottomRight,
    quad.bottomLeft,
  ];
  let sign = 0;
  for (let index = 0; index < points.length; index += 1) {
    const current = points[index];
    const next = points[(index + 1) % points.length];
    const after = points[(index + 2) % points.length];
    const cross = (
      (next.x - current.x) * (after.y - next.y)
      - (next.y - current.y) * (after.x - next.x)
    );
    if (Math.abs(cross) < 0.001) continue;
    const nextSign = Math.sign(cross);
    if (sign !== 0 && nextSign !== sign) return false;
    sign = nextSign;
  }
  return sign !== 0;
}

function polygonArea(points: Point[]): number {
  let area = 0;
  for (let index = 0; index < points.length; index += 1) {
    const next = points[(index + 1) % points.length];
    area += points[index].x * next.y - next.x * points[index].y;
  }
  return Math.abs(area) / 2;
}

function distance(first: Point, second: Point): number {
  return Math.hypot(second.x - first.x, second.y - first.y);
}

function radiansToDegrees(radians: number): number {
  return radians * (180 / Math.PI);
}

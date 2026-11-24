import type { RectangularPassportFrameStatus, RectangularPassportFrameResult } from "./passport-live.types.ts";
import { PASSPORT_LIVE_THRESHOLDS } from "./passport-live-policy.ts";
import { toGrayscale, roundMetric } from "./camera-pixel-math.ts";
import { createMotionSignature, analyzeExposure, emptyResult } from "./passport-live-pixels.ts";
import { findVerticalBoundary, findHorizontalBoundary } from "./passport-live-boundary-search.ts";
import { analyzeInteriorDetail } from "./passport-live-detail.ts";
import { createDocumentQuad, measureDocumentGeometry } from "./passport-live-geometry.ts";

/** Deterministic edge-only analysis used by the browser adapter and tests. */
export function analyzeRectangularPassportFramePixels(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
): RectangularPassportFrameResult {
  if (
    width < 40
    || height < 30
    || pixels.length < width * height * 4
  ) {
    return emptyResult("checking");
  }

  const gray = toGrayscale(pixels, width, height);
  const left = findVerticalBoundary(
    gray,
    width,
    height,
    "left",
  );
  const right = findVerticalBoundary(
    gray,
    width,
    height,
    "right",
  );
  const top = findHorizontalBoundary(
    gray,
    width,
    height,
    "top",
  );
  const bottom = findHorizontalBoundary(
    gray,
    width,
    height,
    "bottom",
  );
  const boundaries = [left, right, top, bottom];
  const visibleEdges = boundaries.filter(Boolean).length;
  const strongEdges = boundaries.filter(
    (boundary) => boundary?.strength === "strong",
  ).length;
  const quad = left && right && top && bottom
    ? createDocumentQuad(left, right, top, bottom)
    : null;
  const geometry = quad && left && right && top && bottom
    ? measureDocumentGeometry(
        quad,
        left,
        right,
        top,
        bottom,
        width,
        height,
      )
    : null;
  const detail = quad
    ? analyzeInteriorDetail(gray, width, height, quad)
    : { tileRatio: 0, rowCoverage: 0 };
  const hasCompleteBoundaryEvidence = visibleEdges === 4
    && strongEdges >= PASSPORT_LIVE_THRESHOLDS.minimumStrongEdges;
  const hasDistributedInteriorDetail = (
    detail.tileRatio
      >= PASSPORT_LIVE_THRESHOLDS.minimumDetailedTileRatio
    && detail.rowCoverage
      >= PASSPORT_LIVE_THRESHOLDS.minimumDetailedRowCoverage
  );
  const isDetected = hasCompleteBoundaryEvidence
    && Boolean(geometry?.isGuideAligned)
    && hasDistributedInteriorDetail;
  const boundaryConfidence = boundaries.reduce(
    (sum, boundary) => sum + (boundary?.score ?? 0),
    0,
  ) / 4;
  const confidence = isDetected
    ? Math.min(
        1,
        boundaryConfidence * 0.67
          + Math.min(1, detail.tileRatio / 0.5) * 0.13
          + 0.2,
      )
    : Math.min(0.82, boundaryConfidence * 0.68);
  const exposure = analyzeExposure(gray);
  const motionSignature = createMotionSignature(gray, width, height);
  const status: RectangularPassportFrameStatus = isDetected
    ? "ready"
    : hasCompleteBoundaryEvidence
      && geometry?.hasExcessiveSkew
      ? "excessive_skew"
      : hasCompleteBoundaryEvidence
        && geometry?.isGuideAligned
        && !hasDistributedInteriorDetail
        ? "not_passport_page"
      : visibleEdges >= 1
        ? "incomplete_document"
        : "no_document";

  return {
    isDetected,
    confidence: roundMetric(confidence),
    visibleEdges,
    strongEdges,
    documentAreaRatio: roundMetric(geometry?.areaRatio ?? 0),
    skewDegrees: roundMetric(geometry?.skewDegrees ?? 0),
    detailTileRatio: roundMetric(detail.tileRatio),
    detailRowCoverage: roundMetric(detail.rowCoverage),
    ...exposure,
    motionSignature,
    status,
  };
}

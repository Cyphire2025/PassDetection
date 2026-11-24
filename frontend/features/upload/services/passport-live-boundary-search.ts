import type { BoundaryEvidence } from "./passport-live.types.ts";
import { PASSPORT_LIVE_THRESHOLDS, GUIDE_EDGE_MIN_RATIO, GUIDE_EDGE_MAX_RATIO } from "./passport-live-policy.ts";
import { roundMetric } from "./camera-pixel-math.ts";
import { evaluateBoundaryCandidate } from "./passport-live-boundary-evidence.ts";

export function findVerticalBoundary(
  gray: Uint8Array,
  width: number,
  height: number,
  side: "left" | "right",
): BoundaryEvidence | null {
  return findBoundary(
    gray,
    width,
    height,
    "vertical",
    side,
    side === "left" ? GUIDE_EDGE_MIN_RATIO : GUIDE_EDGE_MAX_RATIO,
  );
}

export function findHorizontalBoundary(
  gray: Uint8Array,
  width: number,
  height: number,
  side: "top" | "bottom",
): BoundaryEvidence | null {
  return findBoundary(
    gray,
    width,
    height,
    "horizontal",
    side,
    side === "top" ? GUIDE_EDGE_MIN_RATIO : GUIDE_EDGE_MAX_RATIO,
  );
}

function findBoundary(
  gray: Uint8Array,
  width: number,
  height: number,
  orientation: "vertical" | "horizontal",
  side: "left" | "right" | "top" | "bottom",
  expectedPositionRatio: number,
): BoundaryEvidence | null {
  const dependentSize = orientation === "vertical" ? width : height;
  const independentSize = orientation === "vertical" ? height : width;
  const expectedPosition = expectedPositionRatio * (dependentSize - 1);
  const positionTolerance = Math.max(
    4,
    dependentSize
      * PASSPORT_LIVE_THRESHOLDS.edgePositionToleranceRatio,
  );
  const minimumIntercept = Math.max(
    7,
    Math.floor(expectedPosition - positionTolerance),
  );
  const maximumIntercept = Math.min(
    dependentSize - 8,
    Math.ceil(expectedPosition + positionTolerance),
  );
  const segmentSamples = new Uint16Array(8);
  const segmentSupported = new Uint16Array(8);
  let best: BoundaryEvidence | null = null;

  for (
    let slope = -PASSPORT_LIVE_THRESHOLDS.maximumSearchSlope;
    slope <= PASSPORT_LIVE_THRESHOLDS.maximumSearchSlope + 0.0001;
    slope += PASSPORT_LIVE_THRESHOLDS.searchSlopeStep
  ) {
    for (
      let intercept = minimumIntercept;
      intercept <= maximumIntercept;
      intercept += 2
    ) {
      const evidence = evaluateBoundaryCandidate(
        gray,
        width,
        height,
        orientation,
        side,
        slope,
        intercept,
        expectedPosition,
        positionTolerance,
        independentSize,
        segmentSamples,
        segmentSupported,
      );
      if (!best || evidence.score > best.score) best = evidence;
    }
  }

  if (!best) return null;
  // Candidate search stores the boundary position at the frame centre to make
  // guide alignment independent of slope. Geometry uses the standard line
  // equation, so fold the centre offset into the intercept before returning.
  const standardBoundary = {
    ...best,
    intercept: roundMetric(
      best.intercept - best.slope * ((independentSize - 1) / 2),
    ),
  };
  if (
    best.support >= PASSPORT_LIVE_THRESHOLDS.strongEdgeSupport
    && best.segmentCoverage
      >= PASSPORT_LIVE_THRESHOLDS.strongSegmentCoverage
    && best.polarityConsistency
      >= PASSPORT_LIVE_THRESHOLDS.strongPolarityConsistency
    && best.averageContrast
      >= PASSPORT_LIVE_THRESHOLDS.strongAverageContrast
  ) {
    return { ...standardBoundary, strength: "strong" };
  }
  if (
    best.support >= PASSPORT_LIVE_THRESHOLDS.plausibleEdgeSupport
    && best.segmentCoverage
      >= PASSPORT_LIVE_THRESHOLDS.plausibleSegmentCoverage
    && best.polarityConsistency
      >= PASSPORT_LIVE_THRESHOLDS.plausiblePolarityConsistency
    && best.averageContrast
      >= PASSPORT_LIVE_THRESHOLDS.plausibleAverageContrast
  ) {
    return { ...standardBoundary, strength: "plausible" };
  }
  return null;
}

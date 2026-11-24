import type { BoundaryEvidence } from "./passport-live.types.ts";
import { PASSPORT_LIVE_THRESHOLDS } from "./passport-live-policy.ts";
import { roundMetric } from "./camera-pixel-math.ts";

export function evaluateBoundaryCandidate(
  gray: Uint8Array,
  width: number,
  height: number,
  orientation: "vertical" | "horizontal",
  side: "left" | "right" | "top" | "bottom",
  slope: number,
  intercept: number,
  expectedPosition: number,
  positionTolerance: number,
  independentSize: number,
  segmentSamples: Uint16Array,
  segmentSupported: Uint16Array,
): BoundaryEvidence {
  const firstIndependent = Math.round(independentSize * 0.08);
  const lastIndependent = Math.round(independentSize * 0.92);
  segmentSamples.fill(0);
  segmentSupported.fill(0);
  const segmentCount = segmentSamples.length;
  let samples = 0;
  let supported = 0;
  let positive = 0;
  let negative = 0;
  let contrastTotal = 0;

  for (
    let independent = firstIndependent;
    independent <= lastIndependent;
    independent += 2
  ) {
    const centeredIndependent = independent - (independentSize - 1) / 2;
    const dependent = Math.round(
      intercept + slope * centeredIndependent,
    );
    const contrast = boundaryStepContrast(
      gray,
      width,
      height,
      orientation,
      side,
      dependent,
      independent,
    );
    const segment = Math.min(
      segmentCount - 1,
      Math.floor(
        ((independent - firstIndependent)
          / Math.max(1, lastIndependent - firstIndependent + 1))
          * segmentCount,
      ),
    );
    segmentSamples[segment] += 1;
    samples += 1;
    if (
      Math.abs(contrast)
        < PASSPORT_LIVE_THRESHOLDS.edgeStepContrast
    ) {
      continue;
    }
    supported += 1;
    contrastTotal += Math.abs(contrast);
    segmentSupported[segment] += 1;
    if (contrast >= 0) positive += 1;
    else negative += 1;
  }

  let coveredSegments = 0;
  for (let segment = 0; segment < segmentCount; segment += 1) {
    if (
      segmentSupported[segment]
        / Math.max(1, segmentSamples[segment]) >= 0.3
    ) {
      coveredSegments += 1;
    }
  }
  const support = supported / Math.max(1, samples);
  const segmentCoverage = coveredSegments / segmentCount;
  const averageContrast = contrastTotal / Math.max(1, supported);
  const polarityConsistency = Math.max(positive, negative)
    / Math.max(1, supported);
  const alignment = Math.max(
    0,
    1 - Math.abs(intercept - expectedPosition) / positionTolerance,
  );
  const score = (
    support * 0.48
    + segmentCoverage * 0.22
    + Math.min(1, averageContrast / 34) * 0.18
    + polarityConsistency * 0.08
    + alignment * 0.04
  );
  return {
    slope: roundMetric(slope),
    intercept,
    support: roundMetric(support),
    segmentCoverage: roundMetric(segmentCoverage),
    averageContrast: roundMetric(averageContrast),
    polarityConsistency: roundMetric(polarityConsistency),
    score: roundMetric(score),
    strength: "plausible",
  };
}

/**
 * Measures a broad luminance step across a candidate boundary. Thin text,
 * keyboard legends, and seams normally brighten and darken within this span,
 * while a physical page edge keeps one side consistently different.
 */
function boundaryStepContrast(
  gray: Uint8Array,
  width: number,
  height: number,
  orientation: "vertical" | "horizontal",
  side: "left" | "right" | "top" | "bottom",
  dependent: number,
  independent: number,
): number {
  const nearOffset = 3;
  const farOffset = 6;
  let negativeTotal = 0;
  let positiveTotal = 0;
  let samples = 0;

  for (let offset = nearOffset; offset <= farOffset; offset += 1) {
    if (orientation === "vertical") {
      if (
        dependent - offset < 0
        || dependent + offset >= width
        || independent < 0
        || independent >= height
      ) {
        continue;
      }
      negativeTotal += gray[independent * width + dependent - offset];
      positiveTotal += gray[independent * width + dependent + offset];
    } else {
      if (
        dependent - offset < 0
        || dependent + offset >= height
        || independent < 0
        || independent >= width
      ) {
        continue;
      }
      negativeTotal += gray[(dependent - offset) * width + independent];
      positiveTotal += gray[(dependent + offset) * width + independent];
    }
    samples += 1;
  }
  if (samples === 0) return 0;
  const directionalContrast = (
    positiveTotal - negativeTotal
  ) / samples;
  const positiveDirectionIsInside = side === "left" || side === "top";
  return positiveDirectionIsInside
    ? directionalContrast
    : -directionalContrast;
}

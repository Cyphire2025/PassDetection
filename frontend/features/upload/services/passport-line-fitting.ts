import type { Point, FittedLine } from "./passport-normalization.types.ts";

export function fitRobustLine(
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

import type { VisaPhotoLiveBackgroundEvaluation, VisaPhotoFaceGeometry } from "./visa-quality.types.ts";
import {
  LIVE_MIN_BACKGROUND_LUMINANCE, LIVE_MIN_LIGHT_NEUTRAL_RATIO,
  LIVE_MAX_FAILING_LIGHT_NEUTRAL_ZONES, LIVE_MAX_LUMINANCE_DEVIATION, LIVE_MAX_ZONE_MEAN_SPREAD,
  LIVE_MAX_STRONG_EDGE_RATIO, LIVE_MAX_ROUGH_TEXTURE_RATIO, LIVE_MAX_LINE_COVERAGE,
  LIVE_MAX_STRUCTURED_ZONES, LIVE_MAX_EXTREME_ZONES, LIVE_MAX_REGIONAL_EDGE_RATIO,
  LIVE_MAX_REGIONAL_DARK_RATIO,
} from "./visa-quality-policy.ts";
import { evaluateWhiteBackground } from "./visa-quality-background.ts";

/**
 * Converts face-aware, multi-tile wall evidence into a forgiving live gate.
 *
 * A small fixture, soft shadow, hair spill, or one noisy tile should not keep
 * the manual shutter locked. Dark/coloured walls and widespread structure
 * still block readiness. The exact encoded JPEG is evaluated separately by
 * evaluateFinalVisaPhoto, where mild residual defects become borderline and
 * definite defects remain hard failures.
 */
export function evaluateLiveVisaPhotoBackground(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
  face: VisaPhotoFaceGeometry,
): VisaPhotoLiveBackgroundEvaluation {
  const metrics = evaluateWhiteBackground(pixels, width, height, face);
  const isBroadlyLightNeutral = (
    metrics.averageLuminance >= LIVE_MIN_BACKGROUND_LUMINANCE
    && metrics.lightNeutralRatio >= LIVE_MIN_LIGHT_NEUTRAL_RATIO
    && metrics.failingLightNeutralZoneCount
      <= LIVE_MAX_FAILING_LIGHT_NEUTRAL_ZONES
    && metrics.luminanceDeviation <= LIVE_MAX_LUMINANCE_DEVIATION
    && metrics.zoneMeanSpread <= LIVE_MAX_ZONE_MEAN_SPREAD
  );
  if (!isBroadlyLightNeutral) {
    return { status: "not_white", metrics };
  }

  const hasWidespreadStructure = (
    metrics.strongEdgeRatio > LIVE_MAX_STRONG_EDGE_RATIO
    || metrics.roughTextureRatio > LIVE_MAX_ROUGH_TEXTURE_RATIO
    || metrics.maxLineCoverage > LIVE_MAX_LINE_COVERAGE
    || metrics.structuredZoneCount > LIVE_MAX_STRUCTURED_ZONES
    || metrics.extremeZoneCount > LIVE_MAX_EXTREME_ZONES
    || (
      metrics.maxRegionalEdgeRatio > LIVE_MAX_REGIONAL_EDGE_RATIO
      && metrics.maxRegionalDarkRatio > LIVE_MAX_REGIONAL_DARK_RATIO
    )
  );
  return {
    status: hasWidespreadStructure ? "not_plain" : "white",
    metrics,
  };
}

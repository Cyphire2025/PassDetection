import type { PassportRegionQuality, NormalizedRegion, ScreenEvidence } from "./passport-final.types.ts";
import { PASSPORT_FINAL_THRESHOLDS } from "./passport-final-policy.ts";
import { analyzeRegion } from "./passport-final-regions.ts";

export function detectScreenEvidence(
  pixels: Uint8ClampedArray,
  gray: Uint8Array,
  width: number,
  height: number,
  overall: PassportRegionQuality,
): ScreenEvidence {
  const top = bandMetrics(pixels, gray, width, height, {
    left: 0.04,
    top: 0,
    right: 0.96,
    bottom: 0.075,
  });
  const bottom = bandMetrics(pixels, gray, width, height, {
    left: 0.04,
    top: 0.925,
    right: 0.96,
    bottom: 1,
  });
  const left = bandMetrics(pixels, gray, width, height, {
    left: 0,
    top: 0.06,
    right: 0.055,
    bottom: 0.94,
  });
  const right = bandMetrics(pixels, gray, width, height, {
    left: 0.945,
    top: 0.06,
    right: 1,
    bottom: 0.94,
  });
  const topCenter = bandMetrics(pixels, gray, width, height, {
    left: 0.42,
    top: 0,
    right: 0.58,
    bottom: 0.09,
  });
  const topSides = bandMetrics(pixels, gray, width, height, {
    left: 0.08,
    top: 0,
    right: 0.36,
    bottom: 0.09,
  });

  const darkBands = [top, bottom].filter(
    (band) => band.darkPixelRatio
      >= PASSPORT_FINAL_THRESHOLDS.darkUiBandRatio,
  ).length;
  const darkSideBorders = [left, right].filter(
    (band) => band.darkPixelRatio
      >= PASSPORT_FINAL_THRESHOLDS.bezelDarkRatio,
  ).length;
  const strongUiBar = [top, bottom].some((band) => (
    Math.abs(band.meanLuminance - overall.meanLuminance)
      >= PASSPORT_FINAL_THRESHOLDS.uiBandMeanDifference
    && (
      band.darkPixelRatio >= PASSPORT_FINAL_THRESHOLDS.darkUiBandRatio
      || band.clippedHighlightRatio
        >= PASSPORT_FINAL_THRESHOLDS.brightUiBandRatio
    )
    && band.detailDensity >= 0.025
  ));
  const structuredNeutralUiBar = (
    Math.abs(top.meanLuminance - overall.meanLuminance) >= 24
    && top.meanLuminance >= 45
    && top.meanLuminance <= 215
    && top.contrast >= 40
    && top.detailDensity >= 0.08
  );
  const centeredNotch = topCenter.darkPixelRatio >= 0.42
    && topSides.darkPixelRatio <= 0.18
    && topCenter.meanLuminance + 45 < topSides.meanLuminance;
  const obviousBezel = (
    darkBands >= 1
    && darkSideBorders >= 1
    && overall.meanLuminance >= 72
  );

  let obviousSignals = 0;
  if (strongUiBar || structuredNeutralUiBar) obviousSignals += 1;
  if (centeredNotch) obviousSignals += 1;
  if (obviousBezel) obviousSignals += 1;

  let weakSignals = 0;
  if (darkBands === 1 && !strongUiBar) weakSignals += 1;
  if (darkSideBorders === 1 && !obviousBezel) weakSignals += 1;
  if (
    overall.clippedHighlightRatio > 0.12
    && overall.detailDensity < 0.035
  ) {
    weakSignals += 1;
  }
  return { obviousSignals, weakSignals };
}

function bandMetrics(
  pixels: Uint8ClampedArray,
  gray: Uint8Array,
  width: number,
  height: number,
  region: NormalizedRegion,
) {
  return analyzeRegion(pixels, gray, width, height, region);
}

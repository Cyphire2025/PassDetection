import type { PassportRegionQuality } from "./passport-final.types.ts";
import { PASSPORT_FINAL_THRESHOLDS } from "./passport-final-policy.ts";

export function isExtremeExposure(region: PassportRegionQuality): boolean {
  return (
    region.meanLuminance < PASSPORT_FINAL_THRESHOLDS.extremeDarkMean
    && region.darkPixelRatio > PASSPORT_FINAL_THRESHOLDS.extremeDarkRatio
  ) || (
    region.meanLuminance > PASSPORT_FINAL_THRESHOLDS.extremeBrightMean
    && region.clippedHighlightRatio
      > PASSPORT_FINAL_THRESHOLDS.extremeBrightRatio
  );
}

export function isSeverelyUnreadable(region: PassportRegionQuality): boolean {
  return (
    region.sharpness < PASSPORT_FINAL_THRESHOLDS.severeSharpness
    && region.detailDensity
      < PASSPORT_FINAL_THRESHOLDS.severeDetailDensity
  ) || (
    region.contrast < PASSPORT_FINAL_THRESHOLDS.severeTextContrast
    && region.detailDensity
      < PASSPORT_FINAL_THRESHOLDS.severeDetailDensity
  );
}

export function isSoft(region: PassportRegionQuality): boolean {
  return region.sharpness < PASSPORT_FINAL_THRESHOLDS.softSharpness
    || region.detailDensity
      < PASSPORT_FINAL_THRESHOLDS.softDetailDensity;
}

export function isRegionEffectivelyBlank(
  region: PassportRegionQuality,
): boolean {
  return region.detailDensity < 0.008
    && region.contrast < 8;
}

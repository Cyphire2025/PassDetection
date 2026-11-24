import type { PassportFinalQualityReason, PassportRegionQuality, PassportFinalQualityMetrics, PassportFinalQualityResult } from "./passport-final.types.ts";
import type { CameraValidationOutcome } from "./camera-quality-policy";
import type { PassportPageSide } from "./passport-camera-guide";

export function result(
  outcome: CameraValidationOutcome,
  reason: PassportFinalQualityReason,
  message: string,
  metrics: PassportFinalQualityMetrics,
  confirmationPrompt: string | null = null,
): PassportFinalQualityResult {
  return {
    outcome,
    reason,
    message,
    confirmationPrompt: outcome === "borderline"
      ? confirmationPrompt
      : null,
    metrics,
  };
}

export function borderlineMessage(
  reason: PassportFinalQualityReason,
  pageSide: PassportPageSide,
): string {
  switch (reason) {
    case "slightly_soft":
      return "One part of this passport image is slightly soft. Check the preview carefully before continuing.";
    case "small_reflection":
      return "A small reflection is visible. Continue only if every important detail remains readable.";
    case "lower_resolution":
      return "This image has a lower-than-preferred resolution. Continue only if the printed details remain clear.";
    case "weak_screen_suspicion":
      return "This image has a weak screen-like signal, but no definite phone interface was found. Confirm that it is a direct photo of the physical passport.";
    case "document_area_missing":
      return `The passport ${pageSide} page is close to the edge of the image. Confirm that no important details are cut off.`;
    default:
      return "Check the captured passport carefully before continuing.";
  }
}

export function invalidResult(
  sourceWidth: number,
  sourceHeight: number,
): PassportFinalQualityResult {
  const emptyRegion: PassportRegionQuality = {
    sharpness: 0,
    detailDensity: 0,
    contrast: 0,
    meanLuminance: 0,
    darkPixelRatio: 1,
    clippedHighlightRatio: 0,
  };
  return result(
    "hard_failure",
    "invalid_image",
    "The captured passport image could not be checked. Retake it before continuing.",
    {
      overall: emptyRegion,
      mainDetails: emptyRegion,
      lowerTextBand: emptyRegion,
      portrait: emptyRegion,
      effectiveCoverage: 0,
      strongBoundaryCount: 0,
      missingBoundaryLikely: false,
      obviousScreenSignals: 0,
      weakScreenSignals: 0,
      sourceWidth,
      sourceHeight,
    },
  );
}

import type { PassportFinalQualityReason, PassportFinalQualityMetrics, PassportFinalQualityResult } from "./passport-final.types.ts";
import type { PassportPageSide } from "./passport-camera-guide";
import { PASSPORT_FINAL_THRESHOLDS, FRONT_REGIONS, BACK_REGIONS } from "./passport-final-policy.ts";
import { analyzeRegion } from "./passport-final-regions.ts";
import { toGrayscale, roundMetric } from "./camera-pixel-math.ts";
import { estimateDocumentCoverage } from "./passport-final-boundaries.ts";
import { detectScreenEvidence } from "./passport-final-screen.ts";
import { result, borderlineMessage, invalidResult } from "./passport-final-result.ts";
import { isExtremeExposure, isSeverelyUnreadable, isSoft, isRegionEffectivelyBlank } from "./passport-final-region-rules.ts";

export function analyzePassportFinalPixels(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
  pageSide: PassportPageSide,
  sourceWidth = width,
  sourceHeight = height,
): PassportFinalQualityResult {
  if (
    width < 80
    || height < 50
    || pixels.length < width * height * 4
  ) {
    return invalidResult(sourceWidth, sourceHeight);
  }

  const gray = toGrayscale(pixels, width, height);
  const regions = pageSide === "front" ? FRONT_REGIONS : BACK_REGIONS;
  const overall = analyzeRegion(pixels, gray, width, height, regions.overall);
  const mainDetails = analyzeRegion(
    pixels,
    gray,
    width,
    height,
    regions.mainDetails,
  );
  const lowerTextBand = analyzeRegion(
    pixels,
    gray,
    width,
    height,
    regions.lowerTextBand,
  );
  const portrait = analyzeRegion(
    pixels,
    gray,
    width,
    height,
    regions.portrait,
  );
  const boundaryEstimate = estimateDocumentCoverage(
    gray,
    width,
    height,
  );
  const effectiveCoverage = boundaryEstimate.coverage;
  const screenEvidence = detectScreenEvidence(
    pixels,
    gray,
    width,
    height,
    overall,
  );
  const metrics: PassportFinalQualityMetrics = {
    overall,
    mainDetails,
    lowerTextBand,
    portrait,
    effectiveCoverage: roundMetric(effectiveCoverage),
    strongBoundaryCount: boundaryEstimate.strongBoundaryCount,
    missingBoundaryLikely: boundaryEstimate.missingBoundaryLikely,
    obviousScreenSignals: screenEvidence.obviousSignals,
    weakScreenSignals: screenEvidence.weakSignals,
    sourceWidth,
    sourceHeight,
  };

  if (isExtremeExposure(overall)) {
    return result(
      "hard_failure",
      "extreme_exposure",
      overall.meanLuminance < PASSPORT_FINAL_THRESHOLDS.extremeDarkMean
        ? "The captured passport is extremely dark. Move into brighter, even lighting and retake it."
        : "The captured passport is severely overexposed. Reduce the light and retake it.",
      metrics,
    );
  }

  const aspectRatio = sourceWidth / Math.max(1, sourceHeight);
  if (
    effectiveCoverage < PASSPORT_FINAL_THRESHOLDS.hardMinimumCoverage
  ) {
    return result(
      "hard_failure",
      boundaryEstimate.missingBoundaryLikely
        ? "document_area_missing"
        : "passport_too_small",
      boundaryEstimate.missingBoundaryLikely
        ? "A major part of the passport page appears to be outside the captured image. Keep the full page inside the guide and retake it."
        : "The passport occupies too little of the captured image. Move closer, keep the full page visible, and retake it.",
      metrics,
    );
  }
  if (
    aspectRatio < PASSPORT_FINAL_THRESHOLDS.hardMinimumAspectRatio
    || aspectRatio > PASSPORT_FINAL_THRESHOLDS.hardMaximumAspectRatio
  ) {
    return result(
      "hard_failure",
      "document_area_missing",
      "A major part of the passport page appears to be missing. Keep the full page inside the guide and retake it.",
      metrics,
    );
  }
  if (screenEvidence.obviousSignals >= 1) {
    return result(
      "hard_failure",
      "obvious_screen_recapture",
      "A phone bezel or screen interface is visible. Photograph the physical passport page directly and retake it.",
      metrics,
    );
  }
  if (
    mainDetails.clippedHighlightRatio
      >= PASSPORT_FINAL_THRESHOLDS.severeRegionalGlare
    || lowerTextBand.clippedHighlightRatio
      >= PASSPORT_FINAL_THRESHOLDS.severeRegionalGlare
  ) {
    return result(
      "hard_failure",
      "severe_glare",
      "Severe glare covers the passport details. Tilt the physical passport away from the light and retake it.",
      metrics,
    );
  }

  const mainAreaMissing = isRegionEffectivelyBlank(mainDetails);
  const lowerAreaMissing = isRegionEffectivelyBlank(lowerTextBand);
  const portraitAreaMissing = pageSide === "front"
    && isRegionEffectivelyBlank(portrait);
  if (
    (mainAreaMissing && lowerTextBand.detailDensity >= 0.05)
    || (lowerAreaMissing && mainDetails.detailDensity >= 0.05)
    || (portraitAreaMissing && mainDetails.detailDensity >= 0.05)
  ) {
    return result(
      "hard_failure",
      "document_area_missing",
      portraitAreaMissing
        ? "The passport portrait area is missing from the captured image. Keep the full information page inside the guide and retake it."
        : "A major passport details area is missing from the captured image. Keep the full page inside the guide and retake it.",
      metrics,
    );
  }

  const mainSeverelyUnreadable = isSeverelyUnreadable(mainDetails);
  const lowerSeverelyUnreadable = isSeverelyUnreadable(lowerTextBand);
  if (mainSeverelyUnreadable && lowerSeverelyUnreadable) {
    return result(
      "hard_failure",
      "text_unreadable",
      pageSide === "front"
        ? "The passport number and lower text lines are too blurred to read. Hold steady, let the camera focus, and retake it."
        : "The important details on the passport back page are too blurred to read. Hold steady, let the camera focus, and retake it.",
      metrics,
    );
  }

  const borderlineReasons: PassportFinalQualityReason[] = [];
  if (
    effectiveCoverage
      < PASSPORT_FINAL_THRESHOLDS.borderlineMinimumCoverage
    || boundaryEstimate.missingBoundaryLikely
    || aspectRatio < PASSPORT_FINAL_THRESHOLDS.borderlineMinimumAspectRatio
    || aspectRatio > PASSPORT_FINAL_THRESHOLDS.borderlineMaximumAspectRatio
  ) {
    borderlineReasons.push("document_area_missing");
  }
  if (
    isSoft(mainDetails)
    || isSoft(lowerTextBand)
    || mainSeverelyUnreadable
    || lowerSeverelyUnreadable
  ) {
    borderlineReasons.push("slightly_soft");
  }
  const regionalGlare = Math.max(
    mainDetails.clippedHighlightRatio,
    lowerTextBand.clippedHighlightRatio,
  );
  if (
    regionalGlare
      >= PASSPORT_FINAL_THRESHOLDS.borderlineRegionalGlare
  ) {
    borderlineReasons.push("small_reflection");
  }
  if (
    sourceWidth < PASSPORT_FINAL_THRESHOLDS.preferredMinimumWidth
  ) {
    borderlineReasons.push("lower_resolution");
  }
  if (screenEvidence.weakSignals >= 1) {
    borderlineReasons.push("weak_screen_suspicion");
  }

  if (borderlineReasons.length > 0) {
    const reason = borderlineReasons[0];
    return result(
      "borderline",
      reason,
      borderlineMessage(reason, pageSide),
      metrics,
      pageSide === "front"
        ? "Can you clearly read the passport number and the two lines at the bottom?"
        : "Can you clearly read the address and other printed details on this passport page?",
    );
  }

  return result(
    "pass",
    "ready",
    "The captured passport image is clear enough to continue.",
    metrics,
  );
}

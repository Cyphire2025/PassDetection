import type { CameraValidationOutcome } from "./camera-quality-policy";

export type PassportFinalQualityReason =
  | "ready"
  | "invalid_image"
  | "extreme_exposure"
  | "passport_too_small"
  | "document_area_missing"
  | "text_unreadable"
  | "severe_glare"
  | "obvious_screen_recapture"
  | "slightly_soft"
  | "small_reflection"
  | "lower_resolution"
  | "weak_screen_suspicion";

export interface PassportRegionQuality {
  sharpness: number;
  detailDensity: number;
  contrast: number;
  meanLuminance: number;
  darkPixelRatio: number;
  clippedHighlightRatio: number;
}

export interface PassportFinalQualityMetrics {
  overall: PassportRegionQuality;
  mainDetails: PassportRegionQuality;
  lowerTextBand: PassportRegionQuality;
  portrait: PassportRegionQuality;
  effectiveCoverage: number;
  strongBoundaryCount: number;
  missingBoundaryLikely: boolean;
  obviousScreenSignals: number;
  weakScreenSignals: number;
  sourceWidth: number;
  sourceHeight: number;
}

export interface PassportFinalQualityResult {
  outcome: CameraValidationOutcome;
  reason: PassportFinalQualityReason;
  message: string;
  confirmationPrompt: string | null;
  metrics: PassportFinalQualityMetrics;
}

export interface NormalizedRegion {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

export interface ScreenEvidence {
  obviousSignals: number;
  weakSignals: number;
}

export interface DocumentBoundaryEstimate {
  coverage: number;
  strongBoundaryCount: number;
  missingBoundaryLikely: boolean;
}

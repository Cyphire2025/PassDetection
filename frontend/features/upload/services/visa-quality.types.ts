import type { CameraValidationOutcome } from "./camera-quality-policy";

export interface WhiteBackgroundMetrics {
  isWhite: boolean;
  isLightNeutral: boolean;
  isPlain: boolean;
  failureReason: "not_light_neutral" | "not_plain" | null;
  averageLuminance: number;
  lightNeutralRatio: number;
  strongEdgeRatio: number;
  roughTextureRatio: number;
  luminanceDeviation: number;
  zoneMeanSpread: number;
  maxLineCoverage: number;
  maxRegionalEdgeRatio: number;
  maxRegionalDarkRatio: number;
  evaluatedZoneCount: number;
  failingLightNeutralZoneCount: number;
  structuredZoneCount: number;
  extremeZoneCount: number;
}

export type VisaPhotoLiveBackgroundStatus =
  | "white"
  | "not_white"
  | "not_plain";

export interface VisaPhotoLiveBackgroundEvaluation {
  status: VisaPhotoLiveBackgroundStatus;
  metrics: WhiteBackgroundMetrics;
}

export interface NormalizedPoint {
  x: number;
  y: number;
}

export interface VisaPhotoFaceGeometry {
  centerX: number;
  centerY: number;
  width: number;
  height: number;
  leftEye?: NormalizedPoint;
  rightEye?: NormalizedPoint;
}

export type VisaPhotoFacePlacementStatus =
  | "too_far"
  | "too_close"
  | "off_center"
  | "head_tilt"
  | "ready";

export type VisaPhotoClarityStatus = "good" | "too_dark" | "too_bright" | "blurry";

export interface VisaPhotoClarityMetrics {
  status: VisaPhotoClarityStatus;
  averageLuminance: number;
  darkPixelRatio: number;
  brightPixelRatio: number;
  averageGradient: number;
  highGradientRatio: number;
}

export interface VisaPhotoFallbackCaptureState {
  cameraReady: boolean;
  modelUnavailable: boolean;
  userAcknowledgedRequirements: boolean;
}

export type VisaPhotoFaceCountStatus = "no_face" | "one_face" | "multiple";

export interface VisaPhotoFinalValidation {
  outcome: CameraValidationOutcome;
  message: string;
  faceCount: VisaPhotoFaceCountStatus;
  facePlacement: VisaPhotoFacePlacementStatus | null;
  clarity: VisaPhotoClarityMetrics | null;
  background: WhiteBackgroundMetrics | null;
}

export interface VisaJpegEncoding {
  blob: Blob;
  quality: number;
}

export interface PixelBounds {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

import { type VisaPhotoRejectionReason } from "../services/public-flow-telemetry";
import { type VisaPhotoClarityStatus } from "./visa-selfie-quality";
import { type Detection } from "@mediapipe/face_detection";

export interface VisaSelfieCameraProps {
  onCapture: (file: File) => void;
  onCancel: () => void;
  onTelemetryReason?: (reason: VisaPhotoRejectionReason) => void;
}

export type FaceStatus =
  | "loading"
  | "no_face"
  | "multiple"
  | "too_far"
  | "too_close"
  | "off_center"
  | "head_tilt"
  | "ready"
  | "unavailable";

export type BackgroundStatus = "checking" | "white" | "not_white" | "not_plain";

export type ResolvedBackgroundStatus = Exclude<BackgroundStatus, "checking">;

export type ClarityStatus = "checking" | VisaPhotoClarityStatus;

export interface PendingAnalysis {
  id: number;
  cameraGeneration: number;
  timeoutId: number;
}

export interface PendingFinalAnalysis {
  detectorGeneration: number;
  timeoutId: number;
  resolve: (detections: Detection[]) => void;
  reject: (error: Error) => void;
}

export type CaptureMode = "validated" | "fallback";

export type VisaCameraProfile = "relaxed" | "strict";

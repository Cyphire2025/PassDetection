import { type FaceStatus, type ResolvedBackgroundStatus } from "../components/visa-camera.types";
import { type Detection } from "@mediapipe/face_detection";
import {
  type VisaPhotoFaceGeometry,
  evaluateVisaPhotoFacePlacement,
  type VisaPhotoClarityStatus,
  evaluateVisaPhotoClarity,
  evaluateLiveVisaPhotoBackground,
} from "../components/visa-selfie-quality";
import { ACTIVE_VISA_CAMERA_PROFILE, ANALYSIS_WIDTH, ANALYSIS_HEIGHT } from "../components/visa-camera.constants";
import { evaluateCompatibilityVisaPhotoFace, evaluatePermissiveWhiteBackground } from "../components/visa-selfie-compatibility";
import { getVisaOutputCrop } from "./visa-camera-geometry";

export function faceStatusMessage(status: FaceStatus): string {
  switch (status) {
    case "loading": return "Preparing live photo checks...";
    case "no_face": return "Place one face inside the guide";
    case "multiple": return "Only one person should be visible";
    case "too_far": return "Move closer - your face is too small";
    case "too_close": return "Move back slightly";
    case "off_center": return "Center your head inside the guide";
    case "head_tilt": return "Keep your head straight and look at the camera";
    case "ready": return "Checking the background...";
    case "unavailable": return "Live checks unavailable - retry to continue";
  }
}

export function classifyFace(
  detections: Detection[],
  face: VisaPhotoFaceGeometry | null,
): FaceStatus {
  if (ACTIVE_VISA_CAMERA_PROFILE === "relaxed") {
    return evaluateCompatibilityVisaPhotoFace(detections.length, face);
  }
  if (detections.length > 1) return "multiple";
  if (detections.length === 0 || !face) return "no_face";
  if (face.centerY - face.height / 2 < 0.02) return "too_close";
  return evaluateVisaPhotoFacePlacement(face);
}

export function analyzeVisaPhotoFrame(
  video: HTMLVideoElement,
  guide: HTMLDivElement,
  canvas: HTMLCanvasElement,
  face: VisaPhotoFaceGeometry,
): {
  background: ResolvedBackgroundStatus;
  clarity: VisaPhotoClarityStatus;
} {
  const crop = getVisaOutputCrop(video, guide);
  canvas.width = ANALYSIS_WIDTH;
  canvas.height = ANALYSIS_HEIGHT;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) {
    return {
      background: "not_white",
      clarity: "blurry",
    };
  }

  context.drawImage(video, crop.left, crop.top, crop.width, crop.height, 0, 0, ANALYSIS_WIDTH, ANALYSIS_HEIGHT);
  const pixels = context.getImageData(0, 0, ANALYSIS_WIDTH, ANALYSIS_HEIGHT).data;
  if (ACTIVE_VISA_CAMERA_PROFILE === "relaxed") {
    const background = evaluatePermissiveWhiteBackground(
      pixels,
      ANALYSIS_WIDTH,
      ANALYSIS_HEIGHT,
    );
    return {
      background: background.isLightNeutral ? "white" : "not_white",
      clarity: evaluateVisaPhotoClarity(
        pixels,
        ANALYSIS_WIDTH,
        ANALYSIS_HEIGHT,
        face,
      ).status,
    };
  }

  // Strict live guidance uses the same detected-person-excluded, multi-tile
  // evidence as final validation. The exact encoded photo is then reclassified
  // with stricter pass/borderline/hard-failure rules after capture.
  const backgroundEvaluation = evaluateLiveVisaPhotoBackground(
    pixels,
    ANALYSIS_WIDTH,
    ANALYSIS_HEIGHT,
    face,
  );
  return {
    background: backgroundEvaluation.status,
    clarity: evaluateVisaPhotoClarity(
      pixels,
      ANALYSIS_WIDTH,
      ANALYSIS_HEIGHT,
      face,
    ).status,
  };
}

export function isPageHidden() {
  return document.visibilityState === "hidden";
}

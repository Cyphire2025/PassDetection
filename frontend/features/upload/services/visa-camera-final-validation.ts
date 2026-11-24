import type { Detection } from "@mediapipe/face_detection";
import {
  evaluateFallbackFinalVisaPhoto,
  evaluateFinalVisaPhoto,
  type VisaPhotoFinalValidation,
} from "../components/visa-selfie-quality";
import { ANALYSIS_WIDTH, ANALYSIS_HEIGHT } from "../components/visa-camera.constants";
import type { CaptureMode } from "../components/visa-camera.types";
import { faceGeometryFromFinalDetection } from "./visa-camera-geometry";
import { decodeVisaPhoto } from "./visa-camera-image-encoding";

/** Validate the exact JPEG, releasing the decoded image even if its capture was abandoned. */
export async function validateCapturedVisaPhoto({ blob, finalCanvas, mode, detectFinalFaces, isCurrentCapture }: {
  blob: Blob;
  finalCanvas: HTMLCanvasElement | null;
  mode: CaptureMode;
  detectFinalFaces: (image: HTMLImageElement) => Promise<Detection[]>;
  isCurrentCapture: () => boolean;
}): Promise<VisaPhotoFinalValidation | null> {
  const decoded = await decodeVisaPhoto(blob);
  let validation: VisaPhotoFinalValidation;
  try {
    if (!isCurrentCapture()) return null;

    if (!finalCanvas) {
      throw new Error("The captured Visa Photo could not be checked.");
    }
    finalCanvas.width = ANALYSIS_WIDTH;
    finalCanvas.height = ANALYSIS_HEIGHT;
    const finalContext = finalCanvas.getContext("2d", {
      willReadFrequently: true,
    });
    if (!finalContext) {
      throw new Error("The captured Visa Photo could not be checked.");
    }
    finalContext.drawImage(
      decoded.image,
      0,
      0,
      ANALYSIS_WIDTH,
      ANALYSIS_HEIGHT,
    );
    const pixels = finalContext.getImageData(
      0,
      0,
      ANALYSIS_WIDTH,
      ANALYSIS_HEIGHT,
    ).data;
    if (mode === "fallback") {
      validation = evaluateFallbackFinalVisaPhoto({
        pixels,
        width: ANALYSIS_WIDTH,
        height: ANALYSIS_HEIGHT,
      });
    } else {
      const detections = await detectFinalFaces(decoded.image);
      if (!isCurrentCapture()) return null;
      const face = detections.length === 1
        ? faceGeometryFromFinalDetection(detections[0])
        : null;
      validation = evaluateFinalVisaPhoto({
        faceCount: detections.length,
        face,
        pixels,
        width: ANALYSIS_WIDTH,
        height: ANALYSIS_HEIGHT,
      });
    }
  } finally {
    decoded.close();
  }
  return validation;
}

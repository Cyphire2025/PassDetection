"use client";

import { useEffect } from "react";
import { type VisaSelfieCameraProps } from "../components/visa-camera.types";
import { useVisaCameraState } from "./use-visa-camera-state";
import { useVisaCameraShutdown } from "./use-visa-camera-shutdown";
import { visaPhotoRejectionReason } from "../services/public-flow-telemetry";
import { ACTIVE_VISA_CAMERA_PROFILE } from "../components/visa-camera.constants";
import { useStableTelemetryReason } from "./use-stable-telemetry-reason";
import { useVisaPhotoCapture } from "./use-visa-photo-capture";
import { useVisaDetector } from "./use-visa-detector";
import { useVisaCameraStream } from "./use-visa-camera-stream";
import { useVisaLiveAnalysis } from "./use-visa-live-analysis";
import { useVisaCameraControls } from "./use-visa-camera-controls";
import { isVisaPhotoFallbackCaptureAllowed } from "../components/visa-selfie-quality";
import { faceStatusMessage } from "../services/visa-camera-frame-analysis";

export function useVisaCamera({ onCapture, onCancel, onTelemetryReason = () => undefined }: VisaSelfieCameraProps) {
  const state = useVisaCameraState();
  const shutdown = useVisaCameraShutdown(state);
  const {
    isCameraReady, cameraError, faceStatus, backgroundStatus, clarityStatus, liveReady,
    fallbackAcknowledged, modelError, finalValidation, isProcessing, processingError,
  } = state;

  const {
    stopCameraAfterAnalysis,
  } = shutdown;

  const telemetryReason = visaPhotoRejectionReason({
    cameraUnavailable: Boolean(cameraError),
    qualityModelUnavailable: Boolean(modelError),
    faceStatus,
    backgroundStatus,
    clarityStatus: ACTIVE_VISA_CAMERA_PROFILE === "strict"
      ? clarityStatus
      : "checking",
  });

  useStableTelemetryReason(telemetryReason, onTelemetryReason);
  const takePhoto = useVisaPhotoCapture(state, shutdown);
  useVisaDetector(state);
  useVisaCameraStream(state, shutdown);
  useVisaLiveAnalysis(state, shutdown);
  useEffect(() => {
    return () => {
      void stopCameraAfterAnalysis();
    };
  }, [
    stopCameraAfterAnalysis,
  ]);
  const controls = useVisaCameraControls(state, shutdown, onCancel);
  const ready = liveReady;

  const fallbackCaptureAllowed = isVisaPhotoFallbackCaptureAllowed({
    cameraReady: isCameraReady,
    modelUnavailable: Boolean(modelError),
    userAcknowledgedRequirements: fallbackAcknowledged,
  });

  const canUseCapturedPhoto = ACTIVE_VISA_CAMERA_PROFILE === "relaxed"
    || (
      finalValidation !== null
      && finalValidation.outcome !== "hard_failure"
    );

  const guidance = processingError
    ?? (isProcessing
      ? "Saving your Visa Photo..."
      : modelError
        ? "Live checks unavailable - retry or use the guided fallback below"
        : faceStatus !== "ready"
          ? faceStatusMessage(faceStatus)
          : ACTIVE_VISA_CAMERA_PROFILE === "relaxed"
            ? backgroundStatus === "not_white"
              ? "Use a plain white or off-white wall"
              : ready
                ? "Ready to capture"
                : "Checking the wall behind you..."
            : clarityStatus === "too_dark" || clarityStatus === "too_bright"
              ? "Improve the lighting on your face"
              : clarityStatus === "blurry"
                ? "Hold the camera steady and keep your face in focus"
                : backgroundStatus === "not_plain"
                  ? "Use a light, uncluttered wall"
                  : backgroundStatus === "not_white"
                    ? "Use a plain white or off-white wall"
                    : ready
                      ? "Ready to capture"
                      : "Hold steady while the photo checks finish");
  return { ...state, ...controls, takePhoto, ready, fallbackCaptureAllowed, canUseCapturedPhoto, guidance, onCapture };
}

export type VisaCameraController = ReturnType<typeof useVisaCamera>;

"use client";

import { useCallback } from "react";
import { validateCapturedVisaPhoto } from "../services/visa-camera-final-validation";
import { type VisaCameraState } from "./use-visa-camera-state";
import { type VisaCameraShutdown } from "./use-visa-camera-shutdown";
import { useVisaFinalFaceDetection } from "./use-visa-final-face-detection";
import { type CaptureMode } from "../components/visa-camera.types";
import {
  isVisaPhotoFallbackCaptureAllowed,
  encodeVisaJpegUnderLimit,
} from "../components/visa-selfie-quality";
import { getVisaCaptureCrop } from "../services/visa-camera-geometry";
import { captureBestCameraSource, remapVideoCropToSource } from "../services/camera-capture";
import { CAMERA_QUALITY_POLICY } from "../services/camera-quality-policy";
import { canvasToJpeg } from "../services/visa-camera-image-encoding";
import { ACTIVE_VISA_CAMERA_PROFILE } from "../components/visa-camera.constants";
import { VisaDetectorInferenceError, VISA_CAMERA_SAFE_RETRY_MESSAGE } from "../services/visa-selfie-runtime";

export function useVisaPhotoCapture(state: VisaCameraState, shutdown: VisaCameraShutdown) {
  const {
    captureLifecycle, videoRef, guideRef, captureCanvasRef, analysisCanvasRef, streamRef,
    detectorRef, captureStartedRef, captureReadyRef, detectorGenerationRef, activeAnalysisIdRef,
    isCameraReady, setIsCameraReady, setCameraAttempt, isDetectorReady, setIsDetectorReady,
    fallbackAcknowledged, modelError, setModelError, setInitializationAttempt, setCapturedFile,
    setCapturedPreview, setFinalValidation, setBorderlineConfirmed, setIsProcessing,
    setProcessingError, resetQualityState,
  } = state;

  const {
    stopStream, stopAnalysis, waitForLiveAnalysis, stopCameraAfterAnalysis,
  } = shutdown;

  const detectFinalFaces = useVisaFinalFaceDetection(state, shutdown);

  const takePhoto = useCallback(async (mode: CaptureMode = "validated") => {
    const video = videoRef.current;
    const guide = guideRef.current;
    const canvas = captureCanvasRef.current;
    const validatedCaptureAllowed = mode === "validated"
      && !modelError
      && captureReadyRef.current;
    const fallbackCaptureAllowed = mode === "fallback"
      && isVisaPhotoFallbackCaptureAllowed({
        cameraReady: isCameraReady,
        modelUnavailable: Boolean(modelError),
        userAcknowledgedRequirements: fallbackAcknowledged,
      });
    if (
      !video
      || !guide
      || !canvas
      || !isCameraReady
      || (!validatedCaptureAllowed && !fallbackCaptureAllowed)
      || captureStartedRef.current
    ) return;

    captureStartedRef.current = true;
    const isCurrentCapture = captureLifecycle.begin();
    const captureStream = streamRef.current;
    captureReadyRef.current = false;
    setIsProcessing(true);
    setProcessingError(null);
    setFinalValidation(null);
    setBorderlineConfirmed(false);

    try {
      // Stop scheduling before touching the camera source, then wait for the
      // one serialized live inference to finish while its video is still
      // alive. The final JPEG check uses the same queue below.
      stopAnalysis();
      if (mode === "validated") {
        await waitForLiveAnalysis();
      }
      if (!isCurrentCapture()) return;

      const videoCrop = getVisaCaptureCrop(video, guide);
      const source = await captureBestCameraSource(video, captureStream);
      try {
        if (!isCurrentCapture()) return;
        const sourceCrop = remapVideoCropToSource(
          videoCrop,
          video.videoWidth,
          video.videoHeight,
          source.width,
          source.height,
        );
        canvas.width = CAMERA_QUALITY_POLICY.visaOutputWidth;
        canvas.height = CAMERA_QUALITY_POLICY.visaOutputHeight;
        const context = canvas.getContext("2d");
        if (!context) throw new Error("This browser cannot capture a camera image.");

        // One crop/resize only. No background replacement, skin processing,
        // beautification, sharpening, or fabricated metadata is applied.
        context.drawImage(
          source.image,
          sourceCrop.left,
          sourceCrop.top,
          sourceCrop.width,
          sourceCrop.height,
          0,
          0,
          CAMERA_QUALITY_POLICY.visaOutputWidth,
          CAMERA_QUALITY_POLICY.visaOutputHeight,
        );
      } finally {
        source.close();
      }

      const { blob } = await encodeVisaJpegUnderLimit(
        (quality) => canvasToJpeg(canvas, quality),
        CAMERA_QUALITY_POLICY.maxVisaOutputBytes,
      );
      if (!isCurrentCapture()) return;
      const file = new File([blob], `visa-photo-${Date.now()}.jpg`, {
        type: "image/jpeg",
        lastModified: Date.now(),
      });
      if (ACTIVE_VISA_CAMERA_PROFILE === "relaxed") {
        stopStream(captureStream);
        setIsCameraReady(false);
        setCapturedFile(file);
        setCapturedPreview(URL.createObjectURL(file));
        return;
      }

      const validation = await validateCapturedVisaPhoto({
        blob,
        finalCanvas: analysisCanvasRef.current,
        mode,
        detectFinalFaces,
        isCurrentCapture,
      });
      if (!validation) return;

      // Keep the video/stream alive until MediaPipe has completed the final
      // serialized JPEG inference. Stopping it earlier can fault legacy WASM
      // runtimes in Safari and embedded iPhone browsers.
      if (!isCurrentCapture()) return;
      stopStream(captureStream);
      setIsCameraReady(false);
      setCapturedFile(file);
      setCapturedPreview(URL.createObjectURL(file));
      setFinalValidation(validation);
    } catch (error) {
      if (!isCurrentCapture()) return;
      const detectorError = error instanceof VisaDetectorInferenceError
        ? error
        : null;
      setProcessingError(
        detectorError?.message
        ?? (error instanceof Error
          ? error.message
          : "The Visa Photo could not be saved. Please retry."),
      );
      const failedDetectorGeneration = detectorGenerationRef.current;
      await stopCameraAfterAnalysis();
      if (!isCurrentCapture()) return;
      if (
        detectorError?.resetDetector
        && failedDetectorGeneration === detectorGenerationRef.current
      ) {
        detectorGenerationRef.current += 1;
        detectorRef.current = null;
        activeAnalysisIdRef.current = null;
        setIsDetectorReady(false);
        setModelError(VISA_CAMERA_SAFE_RETRY_MESSAGE);
        setInitializationAttempt((current) => current + 1);
      }
      setIsCameraReady(false);
      resetQualityState(isDetectorReady ? "no_face" : "loading");
      setCameraAttempt((current) => current + 1);
    } finally {
      if (isCurrentCapture()) {
        setIsProcessing(false);
        captureStartedRef.current = false;
      }
    }
  }, [
    videoRef,
    guideRef,
    captureCanvasRef,
    modelError,
    captureReadyRef,
    isCameraReady,
    fallbackAcknowledged,
    captureStartedRef,
    captureLifecycle,
    streamRef,
    setIsProcessing,
    setProcessingError,
    setFinalValidation,
    setBorderlineConfirmed,
    stopAnalysis,
    stopStream,
    setIsCameraReady,
    setCapturedFile,
    setCapturedPreview,
    waitForLiveAnalysis,
    analysisCanvasRef,
    detectFinalFaces,
    detectorGenerationRef,
    stopCameraAfterAnalysis,
    resetQualityState,
    isDetectorReady,
    setCameraAttempt,
    detectorRef,
    activeAnalysisIdRef,
    setIsDetectorReady,
    setModelError,
    setInitializationAttempt,
  ]);
  return takePhoto;
}

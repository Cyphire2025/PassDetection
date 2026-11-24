"use client";

import { useEffect } from "react";
import { type VisaCameraState } from "./use-visa-camera-state";
import { type VisaCameraShutdown } from "./use-visa-camera-shutdown";
import { requestVisaPhotoCamera } from "../components/visa-selfie-quality";
import { isPageHidden } from "../services/visa-camera-frame-analysis";

export function useVisaCameraStream(state: VisaCameraState, shutdown: VisaCameraShutdown) {
  const {
    captureLifecycle, videoRef, streamRef, captureStartedRef, cameraGenerationRef,
    activeAnalysisIdRef, visibilityPausedRef, setIsCameraReady, setMirrorPreview, cameraAttempt,
    setCameraAttempt, isDetectorReady, setCameraError, capturedPreview, setIsProcessing,
    resetQualityState,
  } = state;

  const {
    stopCameraAfterAnalysis,
  } = shutdown;

  useEffect(() => {
    let disposed = false;

    async function startCamera() {
      setIsCameraReady(false);
      setCameraError(null);
      if (document.visibilityState === "hidden") {
        visibilityPausedRef.current = true;
        return;
      }
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        setCameraError("Camera access requires HTTPS, or localhost during development.");
        return;
      }

      try {
        const stream = await requestVisaPhotoCamera((constraints) =>
          navigator.mediaDevices.getUserMedia(constraints)
        );
        if (disposed) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        if (isPageHidden()) {
          stream.getTracks().forEach((track) => track.stop());
          visibilityPausedRef.current = true;
          return;
        }
        streamRef.current = stream;
        const facingMode = stream.getVideoTracks()[0]?.getSettings?.().facingMode;
        setMirrorPreview(facingMode === "user");
        const video = videoRef.current;
        if (video) {
          video.srcObject = stream;
          await video.play().catch(() => undefined);
        }
      } catch (error) {
        console.error("Failed to start Visa Photo camera", error);
        if (disposed) return;
        setCameraError(error instanceof DOMException && error.name === "NotAllowedError"
          ? "Camera permission was blocked. Allow camera access and try again."
          : "A camera could not be started on this device. Retry or return to the upload page.");
      }
    }

    void startCamera();
    return () => {
      disposed = true;
      void stopCameraAfterAnalysis();
    };
  }, [
    cameraAttempt,
    setCameraError,
    setIsCameraReady,
    setMirrorPreview,
    stopCameraAfterAnalysis,
    streamRef,
    videoRef,
    visibilityPausedRef,
  ]);

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        if (capturedPreview) return;
        captureLifecycle.invalidate();
        captureStartedRef.current = false;
        setIsProcessing(false);
        visibilityPausedRef.current = true;
        cameraGenerationRef.current += 1;
        activeAnalysisIdRef.current = null;
        void stopCameraAfterAnalysis();
        setIsCameraReady(false);
        setMirrorPreview(false);
        resetQualityState(isDetectorReady ? "no_face" : "loading");
        return;
      }
      if (!visibilityPausedRef.current || capturedPreview) return;
      visibilityPausedRef.current = false;
      setCameraAttempt((current) => current + 1);
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [
    activeAnalysisIdRef,
    cameraGenerationRef,
    captureLifecycle,
    captureStartedRef,
    capturedPreview,
    isDetectorReady,
    resetQualityState,
    setCameraAttempt,
    setIsCameraReady,
    setIsProcessing,
    setMirrorPreview,
    stopCameraAfterAnalysis,
    visibilityPausedRef,
  ]);

}

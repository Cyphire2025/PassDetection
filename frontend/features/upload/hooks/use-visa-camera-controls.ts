"use client";

import { useEffect } from "react";
import { type VisaCameraState } from "./use-visa-camera-state";
import { type VisaCameraShutdown } from "./use-visa-camera-shutdown";

export function useVisaCameraControls(state: VisaCameraState, shutdown: VisaCameraShutdown, onCancel: () => void) {
  const {
    captureLifecycle, captureStartedRef, cameraGenerationRef, detectorGenerationRef,
    activeAnalysisIdRef, setIsCameraReady, setMirrorPreview, setCameraAttempt, isDetectorReady,
    setIsDetectorReady, setCameraError, setFallbackAcknowledged, setModelError,
    setInitializationAttempt, setCapturedFile, capturedPreview, setCapturedPreview,
    setFinalValidation, setBorderlineConfirmed, isProcessing, setProcessingError,
    resetQualityState,
  } = state;

  const {
    stopCameraAfterAnalysis,
  } = shutdown;

  useEffect(() => {
    return () => {
      if (capturedPreview) URL.revokeObjectURL(capturedPreview);
    };
  }, [
    capturedPreview,
  ]);

  const retake = () => {
    captureLifecycle.invalidate();
    if (capturedPreview) URL.revokeObjectURL(capturedPreview);
    cameraGenerationRef.current += 1;
    activeAnalysisIdRef.current = null;
    setCapturedPreview(null);
    setCapturedFile(null);
    setFinalValidation(null);
    setBorderlineConfirmed(false);
    setProcessingError(null);
    setFallbackAcknowledged(false);
    captureStartedRef.current = false;
    setIsCameraReady(false);
    resetQualityState(isDetectorReady ? "no_face" : "loading");
    setCameraAttempt((current) => current + 1);
  };

  const close = () => {
    captureLifecycle.invalidate();
    void stopCameraAfterAnalysis();
    onCancel();
  };

  const retryCamera = () => {
    if (isProcessing) return;
    captureLifecycle.invalidate();
    cameraGenerationRef.current += 1;
    activeAnalysisIdRef.current = null;
    void stopCameraAfterAnalysis();
    setIsCameraReady(false);
    setMirrorPreview(false);
    setCameraError(null);
    setFallbackAcknowledged(false);
    resetQualityState(isDetectorReady ? "no_face" : "loading");
    setCameraAttempt((current) => current + 1);
  };

  const retryChecks = () => {
    detectorGenerationRef.current += 1;
    activeAnalysisIdRef.current = null;
    setModelError(null);
    setFallbackAcknowledged(false);
    setIsDetectorReady(false);
    resetQualityState("loading");
    setInitializationAttempt((value) => value + 1);
  };
  return { retake, close, retryCamera, retryChecks };
}

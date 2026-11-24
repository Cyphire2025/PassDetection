"use client";

import { useCallback } from "react";
import { type VisaCameraState } from "./use-visa-camera-state";
import {
  waitForVisaInferenceDrain,
  VisaDetectorInferenceError,
  INITIAL_VISA_READINESS,
  VISA_CAMERA_SAFE_RETRY_MESSAGE,
} from "../services/visa-selfie-runtime";
import { CAMERA_STOP_DRAIN_TIMEOUT_MS } from "../components/visa-camera.constants";

export function useVisaCameraShutdown(state: VisaCameraState) {
  const {
    videoRef, streamRef, detectorRef, detectorInferenceQueueRef, animationFrameRef,
    captureReadyRef, detectorGenerationRef, activeAnalysisIdRef, visaReadinessRef,
    setIsDetectorReady, setLiveReady, setModelError, setInitializationAttempt,
  } = state;

  const stopStream = useCallback((stream = streamRef.current) => {
    const video = videoRef.current;
    if (video && video.srcObject === stream) {
      video.pause();
      video.srcObject = null;
    }
    stream?.getTracks().forEach((track) => track.stop());
    if (streamRef.current === stream) streamRef.current = null;
  }, [
    streamRef,
    videoRef,
  ]);

  const stopAnalysis = useCallback(() => {
    if (animationFrameRef.current !== null) cancelAnimationFrame(animationFrameRef.current);
    animationFrameRef.current = null;
  }, [
    animationFrameRef,
  ]);

  const waitForLiveAnalysis = useCallback(async () => {
    const drained = await waitForVisaInferenceDrain(
      detectorInferenceQueueRef.current,
      CAMERA_STOP_DRAIN_TIMEOUT_MS,
    );
    if (!drained) {
      detectorGenerationRef.current += 1;
      detectorRef.current = null;
      throw new VisaDetectorInferenceError(
        new Error("Live face analysis did not settle before capture."),
      );
    }
  }, [
    detectorGenerationRef,
    detectorInferenceQueueRef,
    detectorRef,
  ]);

  const stopCameraAfterAnalysis = useCallback(async () => {
    stopAnalysis();
    // Drain belongs to this stream. A visibility retry can open a replacement
    // before inference settles, and that replacement must remain attached.
    const stream = streamRef.current;
    const detectorGeneration = detectorGenerationRef.current;
    const drained = await waitForVisaInferenceDrain(
      detectorInferenceQueueRef.current,
      CAMERA_STOP_DRAIN_TIMEOUT_MS,
    );
    if (!drained && detectorGeneration === detectorGenerationRef.current) {
      detectorGenerationRef.current += 1;
      detectorRef.current = null;
      activeAnalysisIdRef.current = null;
      captureReadyRef.current = false;
      visaReadinessRef.current = { ...INITIAL_VISA_READINESS };
      setLiveReady(false);
      setIsDetectorReady(false);
      setModelError(VISA_CAMERA_SAFE_RETRY_MESSAGE);
      setInitializationAttempt((current) => current + 1);
    }
    stopStream(stream);
  }, [
    activeAnalysisIdRef,
    captureReadyRef,
    detectorGenerationRef,
    detectorInferenceQueueRef,
    detectorRef,
    setInitializationAttempt,
    setIsDetectorReady,
    setLiveReady,
    setModelError,
    stopAnalysis,
    stopStream,
    streamRef,
    visaReadinessRef,
  ]);
  return { stopStream, stopAnalysis, waitForLiveAnalysis, stopCameraAfterAnalysis };
}

export type VisaCameraShutdown = ReturnType<typeof useVisaCameraShutdown>;

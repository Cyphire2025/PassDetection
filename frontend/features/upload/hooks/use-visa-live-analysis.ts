"use client";

import { useEffect } from "react";
import { type VisaCameraState } from "./use-visa-camera-state";
import { type VisaCameraShutdown } from "./use-visa-camera-shutdown";
import { INITIAL_VISA_READINESS, VISA_CAMERA_SAFE_RETRY_MESSAGE } from "../services/visa-selfie-runtime";
import { CAMERA_QUALITY_POLICY } from "../services/camera-quality-policy";
import { ANALYSIS_TIMEOUT_MS } from "../components/visa-camera.constants";
import { type PendingAnalysis } from "../components/visa-camera.types";

export function useVisaLiveAnalysis(state: VisaCameraState, shutdown: VisaCameraShutdown) {
  const {
    videoRef, detectorRef, detectorInferenceQueueRef, animationFrameRef, lastAnalysisRef,
    captureReadyRef, cameraGenerationRef, detectorGenerationRef, nextAnalysisIdRef,
    activeAnalysisIdRef, pendingAnalysesRef, faceStatusRef, visaReadinessRef, isCameraReady,
    isDetectorReady, setIsDetectorReady, cameraError, setFaceStatus, setBackgroundStatus,
    setClarityStatus, setLiveReady, setFallbackAcknowledged, setModelError,
    setInitializationAttempt, capturedPreview,
  } = state;

  const {
    stopAnalysis,
  } = shutdown;

  useEffect(() => {
    if (!isCameraReady || !isDetectorReady || capturedPreview || cameraError) return;

    const failAnalysis = (
      detectorGeneration: number,
      cameraGeneration: number,
      analysisId: number,
      error: unknown,
    ) => {
      const queue = pendingAnalysesRef.current.get(detectorGeneration);
      const pendingIndex = queue?.findIndex((item) => item.id === analysisId) ?? -1;
      if (!queue || pendingIndex < 0) return;
      const [pending] = queue.splice(pendingIndex, 1);
      window.clearTimeout(pending.timeoutId);
      if (activeAnalysisIdRef.current === analysisId) {
        activeAnalysisIdRef.current = null;
      }
      if (
        cameraGeneration !== cameraGenerationRef.current
        || detectorGeneration !== detectorGenerationRef.current
      ) return;
      console.error("Visa Photo frame analysis failed", error);
      captureReadyRef.current = false;
      visaReadinessRef.current = { ...INITIAL_VISA_READINESS };
      faceStatusRef.current = "unavailable";
      setFaceStatus("unavailable");
      setBackgroundStatus("checking");
      setClarityStatus("checking");
      setLiveReady(false);
      setFallbackAcknowledged(false);
      setModelError(VISA_CAMERA_SAFE_RETRY_MESSAGE);
      setIsDetectorReady(false);
      setInitializationAttempt((current) => current + 1);
    };

    const analyze = (now: number) => {
      const detector = detectorRef.current;
      const inferenceQueue = detectorInferenceQueueRef.current;
      const video = videoRef.current;
      if (
        detector
        && inferenceQueue
        && video
        && !inferenceQueue.busy
        && activeAnalysisIdRef.current === null
        && now - lastAnalysisRef.current
        >= CAMERA_QUALITY_POLICY.liveAnalysisIntervalMs
      ) {
        lastAnalysisRef.current = now;
        const cameraGeneration = cameraGenerationRef.current;
        const detectorGeneration = detectorGenerationRef.current;
        const analysisId = ++nextAnalysisIdRef.current;
        const timeoutId = window.setTimeout(() => {
          failAnalysis(
            detectorGeneration,
            cameraGeneration,
            analysisId,
            new Error("Visa Photo analysis timed out."),
          );
        }, ANALYSIS_TIMEOUT_MS);
        const pending: PendingAnalysis = {
          id: analysisId,
          cameraGeneration,
          timeoutId,
        };
        activeAnalysisIdRef.current = analysisId;
        const detectorQueue = pendingAnalysesRef.current.get(detectorGeneration) ?? [];
        detectorQueue.push(pending);
        pendingAnalysesRef.current.set(detectorGeneration, detectorQueue);
        void inferenceQueue.run(() => detector.send({ image: video })).catch((error) => {
          failAnalysis(
            detectorGeneration,
            cameraGeneration,
            analysisId,
            error,
          );
        });
      }
      animationFrameRef.current = requestAnimationFrame(analyze);
    };

    animationFrameRef.current = requestAnimationFrame(analyze);
    return stopAnalysis;
  }, [
    activeAnalysisIdRef,
    animationFrameRef,
    cameraError,
    cameraGenerationRef,
    captureReadyRef,
    capturedPreview,
    detectorGenerationRef,
    detectorInferenceQueueRef,
    detectorRef,
    faceStatusRef,
    isCameraReady,
    isDetectorReady,
    lastAnalysisRef,
    nextAnalysisIdRef,
    pendingAnalysesRef,
    setBackgroundStatus,
    setClarityStatus,
    setFaceStatus,
    setFallbackAcknowledged,
    setInitializationAttempt,
    setIsDetectorReady,
    setLiveReady,
    setModelError,
    stopAnalysis,
    videoRef,
    visaReadinessRef,
  ]);

}

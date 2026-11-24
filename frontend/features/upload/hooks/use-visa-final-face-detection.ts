"use client";

import { useCallback } from "react";
import { type Detection } from "@mediapipe/face_detection";
import { type VisaCameraState } from "./use-visa-camera-state";
import { type VisaCameraShutdown } from "./use-visa-camera-shutdown";
import { VisaDetectorInferenceError } from "../services/visa-selfie-runtime";
import { ANALYSIS_TIMEOUT_MS } from "../components/visa-camera.constants";

export function useVisaFinalFaceDetection(state: VisaCameraState, shutdown: VisaCameraShutdown) {
  const {
    detectorRef, detectorInferenceQueueRef, detectorGenerationRef, pendingFinalAnalysisRef,
  } = state;

  const {
    waitForLiveAnalysis,
  } = shutdown;

  const detectFinalFaces = useCallback(async (
    image: HTMLImageElement | HTMLCanvasElement,
  ): Promise<Detection[]> => {
    await waitForLiveAnalysis();
    const detector = detectorRef.current;
    const inferenceQueue = detectorInferenceQueueRef.current;
    const detectorGeneration = detectorGenerationRef.current;
    if (!detector) {
      throw new Error("The final face check is unavailable.");
    }

    let resolveDetections!: (detections: Detection[]) => void;
    let rejectDetections!: (error: Error) => void;
    const detectionsPromise = new Promise<Detection[]>((resolve, reject) => {
      resolveDetections = resolve;
      rejectDetections = reject;
    });
    const timeoutId = window.setTimeout(() => {
      if (pendingFinalAnalysisRef.current?.timeoutId !== timeoutId) return;
      pendingFinalAnalysisRef.current = null;
      rejectDetections(new VisaDetectorInferenceError(
        new Error("The final face check timed out."),
      ));
    }, ANALYSIS_TIMEOUT_MS);
    pendingFinalAnalysisRef.current = {
      detectorGeneration,
      timeoutId,
      resolve: resolveDetections,
      reject: rejectDetections,
    };
    const finalSend = inferenceQueue.run(() => detector.send({ image }));
    void finalSend.catch((error) => {
      if (pendingFinalAnalysisRef.current?.timeoutId !== timeoutId) return;
      window.clearTimeout(timeoutId);
      pendingFinalAnalysisRef.current = null;
      rejectDetections(new VisaDetectorInferenceError(error));
    });
    const detections = await detectionsPromise;
    try {
      await finalSend;
    } catch (error) {
      throw new VisaDetectorInferenceError(error);
    }
    // MediaPipe may invoke onResults just before send() finishes unwinding.
    // Do not let capture tear down the video until the serialized native call
    // itself has settled as well.
    await inferenceQueue.drain();
    return detections;
  }, [
    detectorGenerationRef,
    detectorInferenceQueueRef,
    detectorRef,
    pendingFinalAnalysisRef,
    waitForLiveAnalysis,
  ]);
  return detectFinalFaces;
}

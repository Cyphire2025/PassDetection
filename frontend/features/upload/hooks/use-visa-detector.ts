"use client";

import { useEffect } from "react";
import { visaFaceDetectionAssetUrl } from "@/config/visa-face-detection-assets";
import { type VisaCameraState } from "./use-visa-camera-state";
import { loadVisaFaceDetection, initializeVisaFaceDetection } from "../services/visa-face-detection-loader";
import { LIVE_FACE_DETECTION_CONFIDENCE, ACTIVE_VISA_CAMERA_PROFILE } from "../components/visa-camera.constants";
import { faceGeometryFromDetection } from "../services/visa-camera-geometry";
import { classifyFace, analyzeVisaPhotoFrame } from "../services/visa-camera-frame-analysis";
import { isVisaPhotoFaceStable, isVisaPhotoFrameCaptureReady } from "../components/visa-selfie-quality";
import { type BackgroundStatus, type ClarityStatus } from "../components/visa-camera.types";
import { updateVisaReadinessHysteresis, VisaDetectorInferenceError } from "../services/visa-selfie-runtime";

export function useVisaDetector(state: VisaCameraState) {
  const {
    videoRef, guideRef, analysisCanvasRef, detectorRef, detectorInferenceQueueRef,
    captureStartedRef, captureReadyRef, cameraGenerationRef, detectorGenerationRef,
    activeAnalysisIdRef, pendingAnalysesRef, pendingFinalAnalysisRef, faceStatusRef,
    previousFaceRef, backgroundStatusRef, visaReadinessRef, setIsDetectorReady, setFaceStatus,
    setBackgroundStatus, setClarityStatus, setLiveReady, setFallbackAcknowledged, setModelError,
    initializationAttempt,
  } = state;

  useEffect(() => {
    let disposed = false;
    let detectorInstance:
      | import("@mediapipe/face_detection").FaceDetection
      | null = null;
    let detectorInitialized = false;
    const inferenceQueue = detectorInferenceQueueRef.current;
    const detectorGeneration = ++detectorGenerationRef.current;
    const pendingAnalyses = pendingAnalysesRef.current;
    pendingAnalyses.set(detectorGeneration, []);

    async function initializeDetector() {
      try {
        // One queue is shared across detector generations. A replacement is
        // never initialized while an abandoned generation may still be inside
        // legacy MediaPipe WASM.
        await inferenceQueue.drain();
        if (disposed) return;
        const { FaceDetection } = await loadVisaFaceDetection();
        if (disposed) return;

        const detector = new FaceDetection({ locateFile: visaFaceDetectionAssetUrl });
        detectorInstance = detector;
        detector.setOptions({
          model: "short",
          selfieMode: false,
          // The short-range model is right for a portrait, but 0.68 produced
          // avoidable misses in Safari and in-app browsers. Final validation
          // still reruns face count, placement, clarity, and background checks
          // on the exact encoded JPEG.
          minDetectionConfidence: LIVE_FACE_DETECTION_CONFIDENCE,
        });
        detector.onResults((results) => {
          const pendingFinal = pendingFinalAnalysisRef.current;
          if (pendingFinal?.detectorGeneration === detectorGeneration) {
            window.clearTimeout(pendingFinal.timeoutId);
            pendingFinalAnalysisRef.current = null;
            pendingFinal.resolve(results.detections);
            return;
          }
          const pending = pendingAnalyses.get(detectorGeneration)?.shift();
          if (!pending) return;
          window.clearTimeout(pending.timeoutId);
          if (activeAnalysisIdRef.current === pending.id) {
            activeAnalysisIdRef.current = null;
          }
          if (
            detectorGeneration !== detectorGenerationRef.current
            || disposed
            || captureStartedRef.current
            || pending.cameraGeneration !== cameraGenerationRef.current
          ) return;

          const video = videoRef.current;
          const guide = guideRef.current;
          const analysisCanvas = analysisCanvasRef.current;
          if (!video || !guide || !analysisCanvas || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return;

          const face = results.detections.length === 1
            ? faceGeometryFromDetection(results.detections[0], video, guide)
            : null;
          const nextFaceStatus = classifyFace(results.detections, face);
          const faceIsStable = ACTIVE_VISA_CAMERA_PROFILE === "relaxed"
            ? true
            : nextFaceStatus === "ready" && face
              ? isVisaPhotoFaceStable(previousFaceRef.current, face)
              : false;
          previousFaceRef.current = nextFaceStatus === "ready"
            ? face
            : null;
          let nextBackgroundStatus: BackgroundStatus = "checking";
          let nextClarityStatus: ClarityStatus = "checking";
          let currentFrameReady = false;

          if (nextFaceStatus === "ready" && face) {
            const frame = analyzeVisaPhotoFrame(
              video,
              guide,
              analysisCanvas,
              face,
            );
            nextBackgroundStatus = frame.background;
            nextClarityStatus = frame.clarity;
            currentFrameReady = ACTIVE_VISA_CAMERA_PROFILE === "relaxed"
              ? nextBackgroundStatus === "white"
              : isVisaPhotoFrameCaptureReady(
                nextBackgroundStatus,
                nextClarityStatus,
              ) && faceIsStable;
          }

          const readiness = updateVisaReadinessHysteresis(
            visaReadinessRef.current,
            currentFrameReady,
          );
          visaReadinessRef.current = readiness;
          const isReady = readiness.ready;

          if (faceStatusRef.current !== nextFaceStatus) {
            faceStatusRef.current = nextFaceStatus;
            setFaceStatus(nextFaceStatus);
          }
          if (backgroundStatusRef.current !== nextBackgroundStatus) {
            backgroundStatusRef.current = nextBackgroundStatus;
            setBackgroundStatus(nextBackgroundStatus);
          }
          setClarityStatus((current) =>
            current === nextClarityStatus ? current : nextClarityStatus
          );
          setLiveReady((current) => current === isReady ? current : isReady);
          captureReadyRef.current = isReady;
        });
        await initializeVisaFaceDetection(detector);
        detectorInitialized = true;
        if (disposed) {
          await detector.close();
          return;
        }
        detectorRef.current = detector;
        activeAnalysisIdRef.current = null;
        setModelError(null);
        setFallbackAcknowledged(false);
        setIsDetectorReady(true);
      } catch (error) {
        console.error("Visa Photo face detection initialization failed", error);
        if (detectorInstance && !detectorInitialized) {
          await detectorInstance.close().catch(() => undefined);
        }
        if (disposed) return;
        faceStatusRef.current = "unavailable";
        setFaceStatus("unavailable");
        captureReadyRef.current = false;
        setFallbackAcknowledged(false);
        setModelError("Live photo checks could not start. Retry them, or use the guided fallback below.");
      }
    }

    void initializeDetector();
    return () => {
      disposed = true;
      pendingAnalyses.get(detectorGeneration)?.forEach((pending) => {
        window.clearTimeout(pending.timeoutId);
      });
      const pendingFinal = pendingFinalAnalysisRef.current;
      if (pendingFinal?.detectorGeneration === detectorGeneration) {
        window.clearTimeout(pendingFinal.timeoutId);
        pendingFinalAnalysisRef.current = null;
        pendingFinal.reject(new VisaDetectorInferenceError(
          new Error("The final face check was interrupted."),
        ));
      }
      pendingAnalyses.delete(detectorGeneration);
      if (detectorRef.current === detectorInstance) {
        detectorRef.current = null;
      }
      if (detectorInstance && detectorInitialized) {
        const detector = detectorInstance;
        void inferenceQueue.drain()
          .then(() => detector.close())
          .catch((error) => {
            console.error("Visa Photo face detector cleanup failed", error);
          });
      }
    };
  }, [
    activeAnalysisIdRef,
    analysisCanvasRef,
    backgroundStatusRef,
    cameraGenerationRef,
    captureReadyRef,
    captureStartedRef,
    detectorGenerationRef,
    detectorInferenceQueueRef,
    detectorRef,
    faceStatusRef,
    guideRef,
    initializationAttempt,
    pendingAnalysesRef,
    pendingFinalAnalysisRef,
    previousFaceRef,
    setBackgroundStatus,
    setClarityStatus,
    setFaceStatus,
    setFallbackAcknowledged,
    setIsDetectorReady,
    setLiveReady,
    setModelError,
    videoRef,
    visaReadinessRef,
  ]);

}

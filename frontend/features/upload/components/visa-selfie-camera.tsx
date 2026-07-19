"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Image from "next/image";
import { AlertTriangle, Check, Loader2, RefreshCcw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Detection } from "@mediapipe/face_detection";
import { useStableTelemetryReason } from "../hooks/use-stable-telemetry-reason";
import {
  visaPhotoRejectionReason,
  type VisaPhotoRejectionReason,
} from "../services/public-flow-telemetry";
import {
  encodeVisaJpegUnderLimit,
  evaluateFallbackFinalVisaPhoto,
  evaluateFinalVisaPhoto,
  evaluateLiveVisaPhotoBackground,
  evaluateVisaPhotoFacePlacement,
  evaluateVisaPhotoClarity,
  isVisaPhotoFrameCaptureReady,
  isVisaPhotoFaceStable,
  isVisaPhotoFallbackCaptureAllowed,
  requestVisaPhotoCamera,
  type VisaPhotoFinalValidation,
  type VisaPhotoClarityStatus,
  type VisaPhotoFaceGeometry,
} from "./visa-selfie-quality";
import {
  evaluateCompatibilityVisaPhotoFace,
  evaluatePermissiveWhiteBackground,
} from "./visa-selfie-compatibility";
import {
  captureBestCameraSource,
  remapVideoCropToSource,
} from "../services/camera-capture";
import {
  CAMERA_QUALITY_POLICY,
  updateRollingCameraReadiness,
} from "../services/camera-quality-policy";

interface VisaSelfieCameraProps {
  onCapture: (file: File) => void;
  onCancel: () => void;
  onTelemetryReason?: (reason: VisaPhotoRejectionReason) => void;
}

type FaceStatus =
  | "loading"
  | "no_face"
  | "multiple"
  | "too_far"
  | "too_close"
  | "off_center"
  | "head_tilt"
  | "ready"
  | "unavailable";
type BackgroundStatus = "checking" | "white" | "not_white" | "not_plain";
type ResolvedBackgroundStatus = Exclude<BackgroundStatus, "checking">;
type ClarityStatus = "checking" | VisaPhotoClarityStatus;

interface PendingAnalysis {
  id: number;
  cameraGeneration: number;
  timeoutId: number;
}

interface PendingFinalAnalysis {
  timeoutId: number;
  resolve: (detections: Detection[]) => void;
  reject: (error: Error) => void;
}

type CaptureMode = "validated" | "fallback";
type VisaCameraProfile = "relaxed" | "strict";

const ANALYSIS_TIMEOUT_MS = 6_000;
const ANALYSIS_WIDTH = 96;
const ANALYSIS_HEIGHT = 144;
const LIVE_FACE_DETECTION_CONFIDENCE = 0.55;
/**
 * The relaxed profile restores the forgiving Visa camera behavior that was
 * active before 9f0e751: one reasonably positioned face plus a white or
 * off-white wall. The newer strict implementation remains fully wired behind
 * this switch so it can be refined and enabled again later.
 */
const ACTIVE_VISA_CAMERA_PROFILE: VisaCameraProfile = "relaxed";

export function VisaSelfieCamera({
  onCapture,
  onCancel,
  onTelemetryReason = () => undefined,
}: VisaSelfieCameraProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const guideRef = useRef<HTMLDivElement>(null);
  const captureCanvasRef = useRef<HTMLCanvasElement>(null);
  const analysisCanvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const detectorRef = useRef<import("@mediapipe/face_detection").FaceDetection | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const lastAnalysisRef = useRef(0);
  const analysisBusyRef = useRef(false);
  const captureStartedRef = useRef(false);
  const captureReadyRef = useRef(false);
  const cameraGenerationRef = useRef(0);
  const detectorGenerationRef = useRef(0);
  const nextAnalysisIdRef = useRef(0);
  const activeAnalysisIdRef = useRef<number | null>(null);
  const pendingAnalysesRef = useRef(new Map<number, PendingAnalysis[]>());
  const pendingFinalAnalysisRef = useRef<PendingFinalAnalysis | null>(null);
  const faceStatusRef = useRef<FaceStatus>("loading");
  const previousFaceRef = useRef<VisaPhotoFaceGeometry | null>(null);
  const backgroundStatusRef = useRef<BackgroundStatus>("checking");
  const readinessSamplesRef = useRef<boolean[]>([]);
  const visibilityPausedRef = useRef(false);

  const [isCameraReady, setIsCameraReady] = useState(false);
  const [mirrorPreview, setMirrorPreview] = useState(false);
  const [cameraAttempt, setCameraAttempt] = useState(0);
  const [isDetectorReady, setIsDetectorReady] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [faceStatus, setFaceStatus] = useState<FaceStatus>("loading");
  const [backgroundStatus, setBackgroundStatus] = useState<BackgroundStatus>("checking");
  const [clarityStatus, setClarityStatus] = useState<ClarityStatus>("checking");
  const [liveReady, setLiveReady] = useState(false);
  const [fallbackAcknowledged, setFallbackAcknowledged] = useState(false);
  const [modelError, setModelError] = useState<string | null>(null);
  const [initializationAttempt, setInitializationAttempt] = useState(0);
  const [capturedFile, setCapturedFile] = useState<File | null>(null);
  const [capturedPreview, setCapturedPreview] = useState<string | null>(null);
  const [finalValidation, setFinalValidation] =
    useState<VisaPhotoFinalValidation | null>(null);
  const [borderlineConfirmed, setBorderlineConfirmed] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingError, setProcessingError] = useState<string | null>(null);

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

  const resetQualityState = useCallback((status: FaceStatus = "loading") => {
    faceStatusRef.current = status;
    previousFaceRef.current = null;
    backgroundStatusRef.current = "checking";
    captureReadyRef.current = false;
    readinessSamplesRef.current = [];
    setFaceStatus(status);
    setBackgroundStatus("checking");
    setClarityStatus("checking");
    setLiveReady(false);
  }, []);

  const stopStream = useCallback(() => {
    if (videoRef.current) {
      videoRef.current.pause();
      videoRef.current.srcObject = null;
    }
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const stopAnalysis = useCallback(() => {
    if (animationFrameRef.current !== null) cancelAnimationFrame(animationFrameRef.current);
    animationFrameRef.current = null;
  }, []);

  const waitForLiveAnalysis = useCallback(async () => {
    const deadline = performance.now() + 1_000;
    while (analysisBusyRef.current && performance.now() < deadline) {
      await nextAnimationFrame();
    }
    if (analysisBusyRef.current) {
      throw new Error("The final face check could not start. Please retake the photo.");
    }
  }, []);

  const detectFinalFaces = useCallback(async (
    image: HTMLImageElement | HTMLCanvasElement,
  ): Promise<Detection[]> => {
    await waitForLiveAnalysis();
    const detector = detectorRef.current;
    if (!detector) {
      throw new Error("The final face check is unavailable.");
    }

    return new Promise<Detection[]>((resolve, reject) => {
      const timeoutId = window.setTimeout(() => {
        if (pendingFinalAnalysisRef.current?.timeoutId !== timeoutId) return;
        pendingFinalAnalysisRef.current = null;
        analysisBusyRef.current = false;
        reject(new Error("The final face check timed out. Please retake the photo."));
      }, ANALYSIS_TIMEOUT_MS);
      pendingFinalAnalysisRef.current = { timeoutId, resolve, reject };
      analysisBusyRef.current = true;
      void detector.send({ image }).catch((error) => {
        if (pendingFinalAnalysisRef.current?.timeoutId !== timeoutId) return;
        window.clearTimeout(timeoutId);
        pendingFinalAnalysisRef.current = null;
        analysisBusyRef.current = false;
        reject(error instanceof Error
          ? error
          : new Error("The final face check failed."));
      });
    });
  }, [waitForLiveAnalysis]);

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
    captureReadyRef.current = false;
    setIsProcessing(true);
    setProcessingError(null);
    setFinalValidation(null);
    setBorderlineConfirmed(false);

    try {
      const videoCrop = getVisaOutputCrop(video, guide);
      const source = await captureBestCameraSource(video, streamRef.current);
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

      try {
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

      stopAnalysis();
      stopStream();
      setIsCameraReady(false);
      const { blob } = await encodeVisaJpegUnderLimit(
        (quality) => canvasToJpeg(canvas, quality),
        CAMERA_QUALITY_POLICY.maxVisaOutputBytes,
      );
      const file = new File([blob], `visa-photo-${Date.now()}.jpg`, {
        type: "image/jpeg",
        lastModified: Date.now(),
      });
      if (ACTIVE_VISA_CAMERA_PROFILE === "relaxed") {
        setCapturedFile(file);
        setCapturedPreview(URL.createObjectURL(file));
        return;
      }

      const decoded = await decodeVisaPhoto(blob);
      let validation: VisaPhotoFinalValidation;
      try {
        const finalCanvas = analysisCanvasRef.current;
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

      setCapturedFile(file);
      setCapturedPreview(URL.createObjectURL(file));
      setFinalValidation(validation);
    } catch (error) {
      setProcessingError(error instanceof Error ? error.message : "The Visa Photo could not be saved. Please retry.");
      stopAnalysis();
      stopStream();
      setIsCameraReady(false);
      resetQualityState(isDetectorReady ? "no_face" : "loading");
      setCameraAttempt((current) => current + 1);
    } finally {
      setIsProcessing(false);
      captureStartedRef.current = false;
    }
  }, [
    fallbackAcknowledged,
    detectFinalFaces,
    isCameraReady,
    isDetectorReady,
    modelError,
    resetQualityState,
    stopAnalysis,
    stopStream,
  ]);

  useEffect(() => {
    let disposed = false;
    const detectorGeneration = ++detectorGenerationRef.current;
    const pendingAnalyses = pendingAnalysesRef.current;
    pendingAnalyses.set(detectorGeneration, []);

    async function initializeDetector() {
      try {
        const { FaceDetection } = await import("@mediapipe/face_detection");
        if (disposed) return;

        const detector = new FaceDetection({ locateFile: (file) => `/mediapipe/face_detection/${file}` });
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
          if (pendingFinal) {
            window.clearTimeout(pendingFinal.timeoutId);
            pendingFinalAnalysisRef.current = null;
            analysisBusyRef.current = false;
            pendingFinal.resolve(results.detections);
            return;
          }
          const pending = pendingAnalyses.get(detectorGeneration)?.shift();
          if (!pending) return;
          window.clearTimeout(pending.timeoutId);
          if (activeAnalysisIdRef.current === pending.id) {
            activeAnalysisIdRef.current = null;
            analysisBusyRef.current = false;
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

          const readiness = updateRollingCameraReadiness(
            readinessSamplesRef.current,
            currentFrameReady,
            captureReadyRef.current,
          );
          readinessSamplesRef.current = readiness.samples;
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
        await detector.initialize();
        if (disposed) {
          await detector.close();
          return;
        }
        detectorRef.current = detector;
        analysisBusyRef.current = false;
        setModelError(null);
        setFallbackAcknowledged(false);
        setIsDetectorReady(true);
      } catch (error) {
        console.error("Visa Photo face detection initialization failed", error);
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
      if (pendingFinal) {
        window.clearTimeout(pendingFinal.timeoutId);
        pendingFinalAnalysisRef.current = null;
        pendingFinal.reject(new Error("The final face check was interrupted."));
      }
      pendingAnalyses.delete(detectorGeneration);
      const detector = detectorRef.current;
      detectorRef.current = null;
      void detector?.close();
    };
  }, [initializationAttempt]);

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
      stopStream();
    };
  }, [cameraAttempt, stopStream]);

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        if (capturedPreview) return;
        visibilityPausedRef.current = true;
        cameraGenerationRef.current += 1;
        activeAnalysisIdRef.current = null;
        analysisBusyRef.current = false;
        stopAnalysis();
        stopStream();
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
    capturedPreview,
    isDetectorReady,
    resetQualityState,
    stopAnalysis,
    stopStream,
  ]);

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
        analysisBusyRef.current = false;
      }
      if (
        cameraGeneration !== cameraGenerationRef.current
        || detectorGeneration !== detectorGenerationRef.current
      ) return;
      console.error("Visa Photo frame analysis failed", error);
      captureReadyRef.current = false;
      readinessSamplesRef.current = [];
      faceStatusRef.current = "unavailable";
      setFaceStatus("unavailable");
      setBackgroundStatus("checking");
      setClarityStatus("checking");
      setLiveReady(false);
      setFallbackAcknowledged(false);
      setModelError("Live photo checks stopped unexpectedly.");
      setIsDetectorReady(false);
    };

    const analyze = (now: number) => {
      const detector = detectorRef.current;
      const video = videoRef.current;
      if (
        detector
        && video
        && !analysisBusyRef.current
        && now - lastAnalysisRef.current
          >= CAMERA_QUALITY_POLICY.liveAnalysisIntervalMs
      ) {
        lastAnalysisRef.current = now;
        analysisBusyRef.current = true;
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
        void detector.send({ image: video }).catch((error) => {
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
  }, [cameraError, capturedPreview, isCameraReady, isDetectorReady, stopAnalysis]);

  useEffect(() => {
    return () => {
      stopAnalysis();
      stopStream();
    };
  }, [stopAnalysis, stopStream]);

  useEffect(() => {
    return () => {
      if (capturedPreview) URL.revokeObjectURL(capturedPreview);
    };
  }, [capturedPreview]);

  const retake = () => {
    if (capturedPreview) URL.revokeObjectURL(capturedPreview);
    cameraGenerationRef.current += 1;
    activeAnalysisIdRef.current = null;
    analysisBusyRef.current = false;
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
    stopAnalysis();
    stopStream();
    onCancel();
  };

  const retryCamera = () => {
    if (isProcessing) return;
    cameraGenerationRef.current += 1;
    activeAnalysisIdRef.current = null;
    analysisBusyRef.current = false;
    stopAnalysis();
    stopStream();
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
    analysisBusyRef.current = false;
    setModelError(null);
    setFallbackAcknowledged(false);
    setIsDetectorReady(false);
    resetQualityState("loading");
    setInitializationAttempt((value) => value + 1);
  };

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

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="visa-photo-camera-title"
      className="fixed inset-0 z-50 flex h-[100dvh] min-h-0 flex-col overflow-hidden bg-slate-50 text-slate-900"
    >
      <header className="z-10 flex min-h-[4.5rem] flex-none items-center justify-between border-b border-slate-200 bg-white px-4 pb-3 pt-[max(0.75rem,env(safe-area-inset-top))] shadow-sm">
        <button type="button" onClick={close} aria-label="Close Visa Photo camera" className="rounded-full border border-slate-200 bg-white p-2 text-slate-600 shadow-sm transition-colors hover:bg-slate-50 hover:text-slate-900">
          <X className="h-6 w-6" />
        </button>
        <div className="text-center">
          <h2 id="visa-photo-camera-title" className="text-base font-semibold text-slate-950">
            Visa Photo Upload
          </h2>
          <p className="text-xs text-slate-500">
            {ACTIVE_VISA_CAMERA_PROFILE === "relaxed"
              ? "Use one face and a plain white or off-white wall"
              : "Remove glasses, keep eyes open, and use a plain light wall"}
          </p>
        </div>
        <div className="w-10" aria-hidden="true" />
      </header>

      <main className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-slate-100">
        {cameraError ? (
          <div
            role="alert"
            className="mx-6 max-w-md rounded-2xl border border-amber-200 bg-white p-6 text-center shadow-xl"
          >
            <AlertTriangle className="mx-auto mb-4 h-10 w-10 text-amber-500" aria-hidden="true" />
            <h3 className="mb-2 text-lg font-semibold text-slate-950">Camera unavailable</h3>
            <p className="mb-6 text-sm leading-6 text-slate-600">{cameraError}</p>
            <div className="flex flex-col gap-3">
              <Button onClick={retryCamera} className="w-full">Retry camera</Button>
              <Button variant="outline" onClick={close} className="w-full border-slate-300 bg-white text-slate-700 hover:bg-slate-50">Back</Button>
            </div>
          </div>
        ) : (
          <>
            <video
              ref={videoRef}
              autoPlay
              muted
              playsInline
              onLoadedData={() => {
                lastAnalysisRef.current = performance.now();
                setIsCameraReady(true);
              }}
              className={`h-full w-full object-cover ${mirrorPreview ? "scale-x-[-1]" : ""} ${capturedPreview ? "opacity-0" : "opacity-100"}`}
            />
            {capturedPreview ? (
              <Image src={capturedPreview} alt="Captured Visa Photo" fill unoptimized className="bg-slate-100 object-contain" />
            ) : (
              <div className="pointer-events-none absolute inset-0">
                {/* The outer frame is a familiar portrait-placement guide. The
                    inner dashed rails are the exact central 2:3 area used for
                    both live analysis and the final 800x1200 capture. */}
                <div
                  data-testid="visa-photo-placement-guide"
                  className="absolute bottom-[clamp(0.75rem,1.75dvh,1.25rem)] left-1/2 aspect-[35/45] w-[72vw] max-w-[26rem] -translate-x-1/2"
                  style={{ width: "min(72vw, 42dvh, 26rem)" }}
                >
                  <div className={`absolute inset-0 rounded-[1.75rem] border-[3px] shadow-[0_0_0_9999px_rgba(248,250,252,0.42)] transition-colors ${ready ? "border-emerald-500" : "border-white"}`} />
                  <div
                    ref={guideRef}
                    data-testid="visa-photo-output-crop"
                    className={`absolute left-1/2 top-0 h-full w-[85.7143%] aspect-[2/3] -translate-x-1/2 border-x border-dashed transition-colors ${ready ? "border-emerald-500/70" : "border-white/55"}`}
                  >
                    <svg
                      aria-hidden="true"
                      viewBox="0 0 100 126"
                      className="absolute inset-x-[4%] bottom-[1%] h-[88%] w-[92%]"
                      preserveAspectRatio="xMidYMax meet"
                    >
                      <path
                        d="M50 3 C32 3 22 19 22 41 C22 59 28 73 38 80 L38 87 C20 89 8 99 5 126 L95 126 C92 99 80 89 62 87 L62 80 C72 73 78 59 78 41 C78 19 68 3 50 3 Z"
                        fill="none"
                        strokeWidth="1.7"
                        strokeDasharray="4 3"
                        vectorEffect="non-scaling-stroke"
                        className={`transition-colors ${ready ? "stroke-emerald-500" : "stroke-white"}`}
                      />
                    </svg>
                  </div>
                </div>
                <div
                  role={processingError ? "alert" : "status"}
                  aria-live={processingError ? "assertive" : "polite"}
                  aria-atomic="true"
                  className={`absolute left-1/2 top-2 w-max max-w-[92%] -translate-x-1/2 rounded-full border px-4 py-2 text-center text-sm font-medium shadow-lg backdrop-blur-md ${processingError ? "border-red-500 bg-red-600 text-white" : ready ? "border-emerald-500 bg-emerald-500 text-white" : "border-slate-200/80 bg-white/90 text-slate-800"}`}
                >
                  {guidance}
                </div>
              </div>
            )}
            {isProcessing && (
              <div
                role="status"
                aria-live="polite"
                className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-3 bg-white/90 px-6 text-center text-slate-900 backdrop-blur-sm"
              >
                <Loader2 className="h-9 w-9 animate-spin text-blue-600" aria-hidden="true" />
                <p className="text-sm font-medium">Saving your Visa Photo</p>
              </div>
            )}
          </>
        )}
        <canvas ref={captureCanvasRef} className="hidden" />
        <canvas ref={analysisCanvasRef} className="hidden" />
      </main>

      {!cameraError && (
        <footer className="z-10 flex max-h-[52dvh] min-h-[8.75rem] flex-none items-center justify-center overflow-y-auto border-t border-slate-200 bg-white px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-3 shadow-[0_-8px_24px_rgba(15,23,42,0.08)]">
          {capturedPreview ? (
            <div className="w-full max-w-md space-y-3">
              {finalValidation && finalValidation.outcome !== "pass" && (
                <div
                  role="alert"
                  className={`flex gap-3 rounded-xl border p-3 text-left ${
                    finalValidation.outcome === "hard_failure"
                      ? "border-red-200 bg-red-50 text-red-950"
                      : "border-amber-200 bg-amber-50 text-amber-950"
                  }`}
                >
                  <AlertTriangle
                    className={`mt-0.5 h-5 w-5 shrink-0 ${
                      finalValidation.outcome === "hard_failure"
                        ? "text-red-600"
                        : "text-amber-600"
                    }`}
                    aria-hidden="true"
                  />
                  <p className="text-xs leading-5">
                    {finalValidation.message}
                  </p>
                </div>
              )}
              {finalValidation?.outcome === "borderline" && (
                <label
                  htmlFor="visa-photo-borderline-confirmation"
                  className="flex cursor-pointer items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-left"
                >
                  <input
                    id="visa-photo-borderline-confirmation"
                    type="checkbox"
                    checked={borderlineConfirmed}
                    onChange={(event) =>
                      setBorderlineConfirmed(event.target.checked)}
                    className="mt-1 h-4 w-4 shrink-0 rounded border-slate-300 text-blue-600 focus:ring-blue-600"
                  />
                  <span className="text-xs leading-5 text-slate-700">
                    I confirm there is exactly one clear, fully visible face
                    with open eyes, and the background is a plain white,
                    off-white, or light-neutral wall.
                  </span>
                </label>
              )}
              <div className="flex flex-col gap-3 sm:flex-row">
                <Button variant="outline" size="lg" onClick={retake} className="flex-1 border-slate-300 bg-white text-slate-700 hover:bg-slate-50">
                  <RefreshCcw className="mr-2 h-4 w-4" /> Retake
                </Button>
                {canUseCapturedPhoto && (
                  <Button
                    size="lg"
                    disabled={
                      finalValidation?.outcome === "borderline"
                      && !borderlineConfirmed
                    }
                    onClick={() => capturedFile && onCapture(capturedFile)}
                    className="flex-1 bg-blue-600 hover:bg-blue-700"
                  >
                    <Check className="mr-2 h-4 w-4" /> Use Visa Photo
                  </Button>
                )}
              </div>
            </div>
          ) : modelError ? (
            <div className="w-full max-w-lg space-y-3 py-1">
              <div
                role="alert"
                className="flex gap-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-left"
              >
                <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
                <div>
                  <p className="text-sm font-semibold text-amber-950">Live checks unavailable</p>
                  <p className="mt-1 text-xs leading-5 text-amber-900">
                    {modelError} Retry the automatic checks, or carefully
                    confirm every requirement before using the guided fallback.
                  </p>
                </div>
              </div>

              <label
                htmlFor="visa-photo-fallback-confirmation"
                className="flex cursor-pointer items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-left"
              >
                <input
                  id="visa-photo-fallback-confirmation"
                  type="checkbox"
                  checked={fallbackAcknowledged}
                  onChange={(event) => setFallbackAcknowledged(event.target.checked)}
                  className="mt-1 h-4 w-4 shrink-0 rounded border-slate-300 text-blue-600 focus:ring-blue-600"
                />
                <span className="text-xs leading-5 text-slate-700">
                  I confirm there is exactly one person, their face is centred,
                  fully visible and sharp, and the background is a plain white
                  or off-white wall with good lighting.
                </span>
              </label>

              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={retryChecks}
                  disabled={isProcessing}
                  className="border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
                >
                  <RefreshCcw className="mr-2 h-4 w-4" />
                  Retry live checks
                </Button>
                <Button
                  type="button"
                  onClick={() => void takePhoto("fallback")}
                  disabled={!fallbackCaptureAllowed || isProcessing}
                  className="bg-blue-600 hover:bg-blue-700"
                >
                  Capture with guided fallback
                </Button>
              </div>
            </div>
          ) : (
            <div className="grid w-full max-w-sm grid-cols-[1fr_auto_1fr] items-center gap-6">
              <div aria-hidden="true" />
              <div className="flex flex-col items-center gap-2 text-center">
                <button
                  type="button"
                  onClick={() => void takePhoto()}
                  disabled={!isCameraReady || isProcessing || !isDetectorReady || !ready}
                  aria-label="Capture Visa Photo manually"
                  className="flex h-[4.5rem] w-[4.5rem] items-center justify-center rounded-full border-4 border-white bg-blue-600 shadow-lg ring-2 ring-blue-600 transition-transform active:scale-95 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:ring-slate-300 disabled:opacity-60"
                >
                  <span className="h-14 w-14 rounded-full border border-white/70" />
                </button>
                <p className="w-40 text-xs leading-4 text-slate-500">
                  {ready
                    ? "Tap the shutter to capture"
                    : "Capture unlocks when positioning checks pass"}
                </p>
              </div>
              <div aria-hidden="true" />
            </div>
          )}
        </footer>
      )}
    </div>
  );
}

function faceStatusMessage(status: FaceStatus): string {
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

function classifyFace(
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

function faceGeometryFromDetection(
  detection: Detection,
  video: HTMLVideoElement,
  guide: HTMLDivElement,
): VisaPhotoFaceGeometry | null {
  const box = detection.boundingBox;
  const crop = getVisaOutputCrop(video, guide);
  const relativeWidth = (box.width * video.videoWidth) / crop.width;
  const relativeHeight = (box.height * video.videoHeight) / crop.height;
  const centerX = (box.xCenter * video.videoWidth - crop.left) / crop.width;
  const centerY = (box.yCenter * video.videoHeight - crop.top) / crop.height;
  if (![relativeWidth, relativeHeight, centerX, centerY].every(Number.isFinite)) {
    return null;
  }

  const eyePoints = detection.landmarks.slice(0, 2).map((landmark) => ({
    x: (landmark.x * video.videoWidth - crop.left) / crop.width,
    y: (landmark.y * video.videoHeight - crop.top) / crop.height,
  }));
  const validEyes = eyePoints.length === 2
    && eyePoints.every((eye) =>
      Number.isFinite(eye.x)
      && Number.isFinite(eye.y)
      && eye.x >= 0
      && eye.x <= 1
      && eye.y >= 0
      && eye.y <= 1
    );
  const orderedEyes = validEyes
    ? [...eyePoints].sort((first, second) => first.x - second.x)
    : [];

  return {
    centerX,
    centerY,
    width: relativeWidth,
    height: relativeHeight,
    ...(validEyes
      ? { leftEye: orderedEyes[0], rightEye: orderedEyes[1] }
      : {}),
  };
}

function faceGeometryFromFinalDetection(
  detection: Detection,
): VisaPhotoFaceGeometry | null {
  const box = detection.boundingBox;
  const values = [box.xCenter, box.yCenter, box.width, box.height];
  if (!values.every(Number.isFinite)) return null;
  const eyePoints = detection.landmarks.slice(0, 2).map((landmark) => ({
    x: landmark.x,
    y: landmark.y,
  }));
  const validEyes = eyePoints.length === 2
    && eyePoints.every((eye) =>
      Number.isFinite(eye.x)
      && Number.isFinite(eye.y)
      && eye.x >= 0
      && eye.x <= 1
      && eye.y >= 0
      && eye.y <= 1
    );
  const orderedEyes = validEyes
    ? [...eyePoints].sort((first, second) => first.x - second.x)
    : [];
  return {
    centerX: box.xCenter,
    centerY: box.yCenter,
    width: box.width,
    height: box.height,
    ...(validEyes
      ? { leftEye: orderedEyes[0], rightEye: orderedEyes[1] }
      : {}),
  };
}

function analyzeVisaPhotoFrame(
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

function canvasToJpeg(
  canvas: HTMLCanvasElement,
  quality: number,
): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (value) => value ? resolve(value) : reject(new Error("Could not save the Visa Photo.")),
      "image/jpeg",
      quality,
    );
  });
}

interface CropBounds {
  left: number;
  top: number;
  width: number;
  height: number;
}

function getVisibleGuideCrop(video: HTMLVideoElement, guide: HTMLDivElement): CropBounds {
  const videoRect = video.getBoundingClientRect();
  const guideRect = guide.getBoundingClientRect();
  const scale = Math.max(videoRect.width / video.videoWidth, videoRect.height / video.videoHeight);
  const renderedWidth = video.videoWidth * scale;
  const renderedHeight = video.videoHeight * scale;
  const offsetX = (renderedWidth - videoRect.width) / 2;
  const offsetY = (renderedHeight - videoRect.height) / 2;

  const left = Math.max(0, (guideRect.left - videoRect.left + offsetX) / scale);
  const top = Math.max(0, (guideRect.top - videoRect.top + offsetY) / scale);
  const width = Math.min(video.videoWidth - left, guideRect.width / scale);
  const height = Math.min(video.videoHeight - top, guideRect.height / scale);
  return { left, top, width: Math.max(1, width), height: Math.max(1, height) };
}

function fitCropToAspect(
  crop: CropBounds,
  targetAspectRatio: number,
): CropBounds {
  const currentAspectRatio = crop.width / crop.height;
  if (currentAspectRatio > targetAspectRatio) {
    const width = crop.height * targetAspectRatio;
    return {
      left: crop.left + (crop.width - width) / 2,
      top: crop.top,
      width,
      height: crop.height,
    };
  }
  const height = crop.width / targetAspectRatio;
  return {
    left: crop.left,
    top: crop.top + (crop.height - height) / 2,
    width: crop.width,
    height,
  };
}

function getVisaOutputCrop(
  video: HTMLVideoElement,
  guide: HTMLDivElement,
): CropBounds {
  return fitCropToAspect(
    getVisibleGuideCrop(video, guide),
    CAMERA_QUALITY_POLICY.visaOutputWidth
      / CAMERA_QUALITY_POLICY.visaOutputHeight,
  );
}

async function decodeVisaPhoto(blob: Blob): Promise<{
  image: HTMLImageElement;
  close: () => void;
}> {
  const objectUrl = URL.createObjectURL(blob);
  const image = new window.Image();
  image.decoding = "async";
  try {
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(
        new Error("The captured Visa Photo could not be decoded."),
      );
      image.src = objectUrl;
    });
    return {
      image,
      close: () => URL.revokeObjectURL(objectUrl),
    };
  } catch (error) {
    URL.revokeObjectURL(objectUrl);
    throw error;
  }
}

function nextAnimationFrame(): Promise<void> {
  return new Promise((resolve) => {
    window.requestAnimationFrame(() => resolve());
  });
}

function isPageHidden() {
  return document.visibilityState === "hidden";
}

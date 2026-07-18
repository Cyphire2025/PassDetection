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
  evaluateVisaPhotoClarity,
  hasStableVisaPhotoReadiness,
  isVisaPhotoFallbackCaptureAllowed,
  requestVisaPhotoCamera,
  type VisaPhotoClarityStatus,
  type VisaPhotoFaceGeometry,
} from "./visa-selfie-quality";
import {
  evaluateCompatibilityVisaPhotoFace,
  evaluatePermissiveWhiteBackground,
} from "./visa-selfie-compatibility";

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

type CaptureMode = "validated" | "fallback";

const OUTPUT_WIDTH = 826;
const OUTPUT_HEIGHT = 1062;
const STABLE_CAPTURE_MS = 2_000;
const ANALYSIS_INTERVAL_MS = 160;
const ANALYSIS_TIMEOUT_MS = 6_000;
const ANALYSIS_WIDTH = 112;
const ANALYSIS_HEIGHT = 144;
const READINESS_SAMPLE_COUNT = 4;

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
  const stableSinceRef = useRef<number | null>(null);
  const captureStartedRef = useRef(false);
  const captureReadyRef = useRef(false);
  const takePhotoRef = useRef<(mode?: CaptureMode) => Promise<void>>(async () => undefined);
  const cameraGenerationRef = useRef(0);
  const detectorGenerationRef = useRef(0);
  const nextAnalysisIdRef = useRef(0);
  const activeAnalysisIdRef = useRef<number | null>(null);
  const pendingAnalysesRef = useRef(new Map<number, PendingAnalysis[]>());
  const faceStatusRef = useRef<FaceStatus>("loading");
  const backgroundStatusRef = useRef<BackgroundStatus>("checking");
  const backgroundSamplesRef = useRef<ResolvedBackgroundStatus[]>([]);
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
  const [countdown, setCountdown] = useState<number | null>(null);
  const [capturedFile, setCapturedFile] = useState<File | null>(null);
  const [capturedPreview, setCapturedPreview] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingError, setProcessingError] = useState<string | null>(null);

  const telemetryReason = visaPhotoRejectionReason({
    cameraUnavailable: Boolean(cameraError),
    qualityModelUnavailable: Boolean(modelError),
    faceStatus,
    backgroundStatus,
    clarityStatus,
  });
  useStableTelemetryReason(telemetryReason, onTelemetryReason);

  const resetQualityState = useCallback((status: FaceStatus = "loading") => {
    faceStatusRef.current = status;
    backgroundStatusRef.current = "checking";
    captureReadyRef.current = false;
    stableSinceRef.current = null;
    backgroundSamplesRef.current = [];
    readinessSamplesRef.current = [];
    setFaceStatus(status);
    setBackgroundStatus("checking");
    setClarityStatus("checking");
    setLiveReady(false);
    setCountdown(null);
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
    stableSinceRef.current = null;
    setCountdown(null);

    try {
      const crop = getVisibleGuideCrop(video, guide);
      canvas.width = OUTPUT_WIDTH;
      canvas.height = OUTPUT_HEIGHT;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("This browser cannot capture a camera image.");

      // The source frame is saved as captured. No synthetic background or edge
      // segmentation is applied; the live checks require a real white backdrop.
      context.drawImage(video, crop.left, crop.top, crop.width, crop.height, 0, 0, OUTPUT_WIDTH, OUTPUT_HEIGHT);
      const blob = await canvasToJpeg(canvas);
      const file = new File([blob], `visa-photo-${Date.now()}.jpg`, {
        type: "image/jpeg",
        lastModified: Date.now(),
      });
      stopAnalysis();
      stopStream();
      setIsCameraReady(false);
      setCapturedFile(file);
      setCapturedPreview(URL.createObjectURL(file));
    } catch (error) {
      setProcessingError(error instanceof Error ? error.message : "The Visa Photo could not be saved. Please retry.");
    } finally {
      setIsProcessing(false);
      captureStartedRef.current = false;
    }
  }, [
    fallbackAcknowledged,
    isCameraReady,
    modelError,
    stopAnalysis,
    stopStream,
  ]);

  useEffect(() => {
    takePhotoRef.current = takePhoto;
  }, [takePhoto]);

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
          minDetectionConfidence: 0.68,
        });
        detector.onResults((results) => {
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
            nextBackgroundStatus = stabilizeBackgroundStatus(
              frame.background,
              backgroundSamplesRef.current,
            );
            nextClarityStatus = frame.clarity;
            currentFrameReady = nextBackgroundStatus === "white";
          } else {
            backgroundSamplesRef.current = [];
          }

          readinessSamplesRef.current.push(currentFrameReady);
          if (readinessSamplesRef.current.length > READINESS_SAMPLE_COUNT) {
            readinessSamplesRef.current.shift();
          }
          const isReady = hasStableVisaPhotoReadiness(
            readinessSamplesRef.current,
            READINESS_SAMPLE_COUNT,
          );

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

          const now = performance.now();
          if (isReady) {
            const stableSince = stableSinceRef.current ?? now;
            stableSinceRef.current = stableSince;
            const remaining = STABLE_CAPTURE_MS - (now - stableSince);
            const nextCountdown = Math.max(1, Math.ceil(remaining / 1_000));
            setCountdown((current) => current === nextCountdown ? current : nextCountdown);
            if (remaining <= 0) void takePhotoRef.current();
          } else {
            stableSinceRef.current = null;
            setCountdown((current) => current === null ? current : null);
          }
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
      if (detector && video && !analysisBusyRef.current && now - lastAnalysisRef.current >= ANALYSIS_INTERVAL_MS) {
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
  const guidance = processingError
    ?? (isProcessing
      ? "Saving your Visa Photo..."
      : modelError
        ? "Live checks unavailable - retry or use the guided fallback below"
        : countdown
        ? `Hold still - capturing in ${countdown}`
        : faceStatus !== "ready"
          ? faceStatusMessage(faceStatus)
          : clarityStatus === "too_dark" || clarityStatus === "too_bright"
            ? "Improve the lighting on your face"
            : clarityStatus === "blurry"
              ? "Hold the camera steady and keep your face in focus"
              : backgroundStatus === "not_plain"
                ? "Use a plain wall without handles, seams, shelves, or patterns"
                : backgroundStatus === "not_white"
                  ? "Use a plain white or off-white wall"
                  : ready
                    ? "All checks passed - hold still"
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
          <p className="text-xs text-slate-500">Live photo quality checks</p>
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
              onLoadedData={() => setIsCameraReady(true)}
              className={`h-full w-full object-cover ${mirrorPreview ? "scale-x-[-1]" : ""} ${capturedPreview ? "opacity-0" : "opacity-100"}`}
            />
            {capturedPreview ? (
              <Image src={capturedPreview} alt="Captured Visa Photo" fill unoptimized className="bg-slate-100 object-contain" />
            ) : (
              <div className="pointer-events-none absolute inset-0">
                {/* Keep a dedicated lane for live guidance while allowing the crop
                    to grow on taller phones. Safe-area insets are removed from
                    the vertical budget so Safari controls never crowd the frame. */}
                <div
                  ref={guideRef}
                  className="absolute bottom-[clamp(0.75rem,1.75dvh,1.25rem)] left-1/2 aspect-[35/45] -translate-x-1/2"
                  style={{
                    width: "max(min(68vw, 45dvh, 27rem), min(84vw, calc(77.7778dvh - 15.5rem - env(safe-area-inset-top) - env(safe-area-inset-bottom)), 31rem))",
                  }}
                >
                  <div className={`absolute inset-0 rounded-[1.75rem] border-[3px] shadow-[0_0_0_9999px_rgba(248,250,252,0.42)] transition-colors ${ready ? "border-emerald-500" : "border-white"}`} />
                  <svg
                    aria-hidden="true"
                    viewBox="0 0 100 126"
                    className="absolute inset-x-[3.5%] bottom-0 top-[3%] h-[97%] w-[93%]"
                    preserveAspectRatio="none"
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
            <div className="flex w-full max-w-md flex-col gap-3 sm:flex-row">
              <Button variant="outline" size="lg" onClick={retake} className="flex-1 border-slate-300 bg-white text-slate-700 hover:bg-slate-50">
                <RefreshCcw className="mr-2 h-4 w-4" /> Retake
              </Button>
              <Button size="lg" onClick={() => capturedFile && onCapture(capturedFile)} className="flex-1 bg-blue-600 hover:bg-blue-700">
                <Check className="mr-2 h-4 w-4" /> Use Visa Photo
              </Button>
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
                <p className="w-40 text-xs leading-4 text-slate-500">{ready ? "Auto-captures after checks stay stable" : "Capture unlocks when all checks pass"}</p>
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
  return evaluateCompatibilityVisaPhotoFace(detections.length, face);
}

function faceGeometryFromDetection(
  detection: Detection,
  video: HTMLVideoElement,
  guide: HTMLDivElement,
): VisaPhotoFaceGeometry | null {
  const box = detection.boundingBox;
  const crop = getVisibleGuideCrop(video, guide);
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

function analyzeVisaPhotoFrame(
  video: HTMLVideoElement,
  guide: HTMLDivElement,
  canvas: HTMLCanvasElement,
  face: VisaPhotoFaceGeometry,
): {
  background: ResolvedBackgroundStatus;
  clarity: VisaPhotoClarityStatus;
} {
  const crop = getVisibleGuideCrop(video, guide);
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
  const backgroundMetrics = evaluatePermissiveWhiteBackground(
    pixels,
    ANALYSIS_WIDTH,
    ANALYSIS_HEIGHT,
  );
  const background = backgroundMetrics.isLightNeutral ? "white" : "not_white";
  return {
    background,
    clarity: evaluateVisaPhotoClarity(
      pixels,
      ANALYSIS_WIDTH,
      ANALYSIS_HEIGHT,
      face,
    ).status,
  };
}

function stabilizeBackgroundStatus(
  sample: ResolvedBackgroundStatus,
  samples: ResolvedBackgroundStatus[],
): BackgroundStatus {
  samples.push(sample);
  if (samples.length > 5) samples.shift();
  if (samples.length < 4) return "checking";

  const latestTwo = samples.slice(-2);
  if (
    latestTwo.every((value) => value === "white")
    && samples.filter((value) => value === "white").length >= 4
  ) {
    return "white";
  }
  for (const failure of ["not_white", "not_plain"] as const) {
    if (
      latestTwo.every((value) => value === failure)
      && samples.filter((value) => value === failure).length >= 3
    ) {
      return failure;
    }
  }
  return "checking";
}

function canvasToJpeg(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (value) => value ? resolve(value) : reject(new Error("Could not save the Visa Photo.")),
      "image/jpeg",
      0.94,
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

function isPageHidden() {
  return document.visibilityState === "hidden";
}

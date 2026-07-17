"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Image from "next/image";
import { AlertTriangle, Check, Loader2, RefreshCcw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Detection } from "@mediapipe/face_detection";
import { evaluateWhiteBackground, isVisaSelfieFaceLargeEnough } from "./visa-selfie-quality";

interface VisaSelfieCameraProps {
  onCapture: (file: File) => void;
  onCancel: () => void;
}

type FacingMode = "user" | "environment";
type FaceStatus = "loading" | "no_face" | "multiple" | "too_far" | "too_close" | "off_center" | "ready" | "unavailable";
type BackgroundStatus = "checking" | "white" | "not_white" | "not_plain";
type ResolvedBackgroundStatus = Exclude<BackgroundStatus, "checking">;

interface PendingAnalysis {
  id: number;
  cameraGeneration: number;
}

const OUTPUT_WIDTH = 826;
const OUTPUT_HEIGHT = 1062;
const STABLE_CAPTURE_MS = 2_000;
const ANALYSIS_INTERVAL_MS = 160;
const ANALYSIS_WIDTH = 72;
const ANALYSIS_HEIGHT = 92;

export function VisaSelfieCamera({ onCapture, onCancel }: VisaSelfieCameraProps) {
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
  const takePhotoRef = useRef<() => Promise<void>>(async () => undefined);
  const cameraGenerationRef = useRef(0);
  const detectorGenerationRef = useRef(0);
  const nextAnalysisIdRef = useRef(0);
  const activeAnalysisIdRef = useRef<number | null>(null);
  const pendingAnalysesRef = useRef(new Map<number, PendingAnalysis[]>());
  const faceStatusRef = useRef<FaceStatus>("loading");
  const backgroundStatusRef = useRef<BackgroundStatus>("checking");
  const backgroundSamplesRef = useRef<ResolvedBackgroundStatus[]>([]);

  const [facingMode, setFacingMode] = useState<FacingMode>("user");
  const [isCameraReady, setIsCameraReady] = useState(false);
  const [isDetectorReady, setIsDetectorReady] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [faceStatus, setFaceStatus] = useState<FaceStatus>("loading");
  const [backgroundStatus, setBackgroundStatus] = useState<BackgroundStatus>("checking");
  const [modelError, setModelError] = useState<string | null>(null);
  const [initializationAttempt, setInitializationAttempt] = useState(0);
  const [countdown, setCountdown] = useState<number | null>(null);
  const [capturedFile, setCapturedFile] = useState<File | null>(null);
  const [capturedPreview, setCapturedPreview] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingError, setProcessingError] = useState<string | null>(null);

  const resetQualityState = useCallback((status: FaceStatus = "loading") => {
    faceStatusRef.current = status;
    backgroundStatusRef.current = "checking";
    captureReadyRef.current = false;
    stableSinceRef.current = null;
    backgroundSamplesRef.current = [];
    setFaceStatus(status);
    setBackgroundStatus("checking");
    setCountdown(null);
  }, []);

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const stopAnalysis = useCallback(() => {
    if (animationFrameRef.current !== null) cancelAnimationFrame(animationFrameRef.current);
    animationFrameRef.current = null;
  }, []);

  const takePhoto = useCallback(async () => {
    const video = videoRef.current;
    const guide = guideRef.current;
    const canvas = captureCanvasRef.current;
    if (!video || !guide || !canvas || !isCameraReady || !captureReadyRef.current || captureStartedRef.current) return;

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
      const file = new File([blob], `visa-selfie-${Date.now()}.jpg`, {
        type: "image/jpeg",
        lastModified: Date.now(),
      });
      setCapturedFile(file);
      setCapturedPreview(URL.createObjectURL(file));
    } catch (error) {
      setProcessingError(error instanceof Error ? error.message : "The selfie could not be saved. Please retry.");
    } finally {
      setIsProcessing(false);
      captureStartedRef.current = false;
    }
  }, [isCameraReady]);

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

          const nextFaceStatus = classifyFace(results.detections, video, guide);
          const nextBackgroundStatus = nextFaceStatus === "ready"
            ? stabilizeBackgroundStatus(
                analyzeWhiteBackground(video, guide, analysisCanvas),
                backgroundSamplesRef.current,
              )
            : "checking";
          if (nextFaceStatus !== "ready") backgroundSamplesRef.current = [];
          const isReady = nextFaceStatus === "ready" && nextBackgroundStatus === "white";

          if (faceStatusRef.current !== nextFaceStatus) {
            faceStatusRef.current = nextFaceStatus;
            setFaceStatus(nextFaceStatus);
          }
          if (backgroundStatusRef.current !== nextBackgroundStatus) {
            backgroundStatusRef.current = nextBackgroundStatus;
            setBackgroundStatus(nextBackgroundStatus);
          }
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
        setIsDetectorReady(true);
      } catch (error) {
        console.error("VISA selfie face detection initialization failed", error);
        if (disposed) return;
        faceStatusRef.current = "unavailable";
        setFaceStatus("unavailable");
        setModelError("Live face and background checks could not start. Retry before taking a photo.");
      }
    }

    void initializeDetector();
    return () => {
      disposed = true;
      pendingAnalyses.delete(detectorGeneration);
      const detector = detectorRef.current;
      detectorRef.current = null;
      void detector?.close();
    };
  }, [initializationAttempt]);

  useEffect(() => {
    let disposed = false;

    async function startCamera() {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        setCameraError("Camera access requires HTTPS, or localhost during development.");
        return;
      }

      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: facingMode },
            width: { ideal: 1920 },
            height: { ideal: 1440 },
          },
          audio: false,
        });
        if (disposed) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        streamRef.current = stream;
        const video = videoRef.current;
        if (video) {
          video.srcObject = stream;
          await video.play().catch(() => undefined);
        }
      } catch (error) {
        console.error("Failed to start VISA selfie camera", error);
        if (disposed) return;
        setCameraError(error instanceof DOMException && error.name === "NotAllowedError"
          ? "Camera permission was blocked. Allow camera access and try again."
          : `The ${facingMode === "user" ? "front" : "back"} camera could not be started on this device.`);
      }
    }

    void startCamera();
    return () => {
      disposed = true;
      stopStream();
    };
  }, [facingMode, stopStream]);

  useEffect(() => {
    if (!isCameraReady || !isDetectorReady || capturedPreview || cameraError) return;

    const analyze = (now: number) => {
      const detector = detectorRef.current;
      const video = videoRef.current;
      if (detector && video && !analysisBusyRef.current && now - lastAnalysisRef.current >= ANALYSIS_INTERVAL_MS) {
        lastAnalysisRef.current = now;
        analysisBusyRef.current = true;
        const cameraGeneration = cameraGenerationRef.current;
        const detectorGeneration = detectorGenerationRef.current;
        const analysisId = ++nextAnalysisIdRef.current;
        const pending = { id: analysisId, cameraGeneration };
        activeAnalysisIdRef.current = analysisId;
        const detectorQueue = pendingAnalysesRef.current.get(detectorGeneration) ?? [];
        detectorQueue.push(pending);
        pendingAnalysesRef.current.set(detectorGeneration, detectorQueue);
        void detector.send({ image: video }).catch((error) => {
          const queue = pendingAnalysesRef.current.get(detectorGeneration);
          const pendingIndex = queue?.findIndex((item) => item.id === analysisId) ?? -1;
          if (queue && pendingIndex >= 0) queue.splice(pendingIndex, 1);
          if (activeAnalysisIdRef.current === analysisId) {
            activeAnalysisIdRef.current = null;
            analysisBusyRef.current = false;
          }
          if (
            cameraGeneration !== cameraGenerationRef.current
            || detectorGeneration !== detectorGenerationRef.current
          ) return;
          console.error("VISA selfie frame analysis failed", error);
          captureReadyRef.current = false;
          faceStatusRef.current = "unavailable";
          setFaceStatus("unavailable");
          setModelError("Live photo checks stopped unexpectedly. Retry the checks to continue.");
          setIsDetectorReady(false);
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
    setCapturedPreview(null);
    setCapturedFile(null);
    setProcessingError(null);
    captureStartedRef.current = false;
    resetQualityState(isDetectorReady ? "no_face" : "loading");
  };

  const close = () => {
    stopAnalysis();
    stopStream();
    onCancel();
  };

  const toggleCamera = () => {
    if (isProcessing) return;
    cameraGenerationRef.current += 1;
    activeAnalysisIdRef.current = null;
    analysisBusyRef.current = false;
    stopAnalysis();
    stopStream();
    setIsCameraReady(false);
    setCameraError(null);
    resetQualityState(isDetectorReady ? "no_face" : "loading");
    setFacingMode((current) => current === "user" ? "environment" : "user");
  };

  const retryChecks = () => {
    detectorGenerationRef.current += 1;
    activeAnalysisIdRef.current = null;
    analysisBusyRef.current = false;
    setModelError(null);
    setIsDetectorReady(false);
    resetQualityState("loading");
    setInitializationAttempt((value) => value + 1);
  };

  const ready = faceStatus === "ready" && backgroundStatus === "white";
  const guidance = processingError
    ?? (isProcessing
      ? "Saving the original camera photo..."
      : countdown
        ? `Hold still - capturing in ${countdown}`
        : faceStatus === "ready" && backgroundStatus === "not_plain"
          ? "The wall is not plain - avoid patterns and texture"
          : faceStatus === "ready" && backgroundStatus === "not_white"
            ? "Use a white or off-white wall - normal room lighting is okay"
          : faceStatusMessage(faceStatus));

  return (
    <div className="fixed inset-0 z-50 flex h-[100dvh] min-h-0 flex-col overflow-hidden bg-slate-50 text-slate-900">
      <header className="z-10 flex min-h-[4.5rem] flex-none items-center justify-between border-b border-slate-200 bg-white px-4 pb-3 pt-[max(0.75rem,env(safe-area-inset-top))] shadow-sm">
        <button type="button" onClick={close} aria-label="Close selfie camera" className="rounded-full border border-slate-200 bg-white p-2 text-slate-600 shadow-sm transition-colors hover:bg-slate-50 hover:text-slate-900">
          <X className="h-6 w-6" />
        </button>
        <div className="text-center">
          <h2 className="text-base font-semibold text-slate-950">VISA Selfie Photo</h2>
          <p className="text-xs text-slate-500">Use a plain white or off-white wall</p>
        </div>
        <div className="w-10" aria-hidden="true" />
      </header>

      <main className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-slate-100">
        {cameraError ? (
          <div className="mx-6 max-w-md rounded-2xl border border-amber-200 bg-white p-6 text-center shadow-xl">
            <AlertTriangle className="mx-auto mb-4 h-10 w-10 text-amber-500" />
            <h3 className="mb-2 text-lg font-semibold text-slate-950">Camera unavailable</h3>
            <p className="mb-6 text-sm leading-6 text-slate-600">{cameraError}</p>
            <div className="flex flex-col gap-3">
              <Button onClick={toggleCamera} className="w-full">Try the {facingMode === "user" ? "back" : "front"} camera</Button>
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
              className={`h-full w-full object-cover ${facingMode === "user" ? "scale-x-[-1]" : ""} ${capturedPreview ? "opacity-0" : "opacity-100"}`}
            />
            {capturedPreview ? (
              <Image src={capturedPreview} alt="Captured VISA selfie" fill unoptimized className="bg-slate-100 object-contain" />
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
                <div className={`absolute left-1/2 top-2 w-max max-w-[92%] -translate-x-1/2 rounded-full border px-4 py-2 text-center text-sm font-medium shadow-lg backdrop-blur-md ${processingError ? "border-red-500 bg-red-600 text-white" : ready ? "border-emerald-500 bg-emerald-500 text-white" : "border-slate-200/80 bg-white/90 text-slate-800"}`}>
                  {guidance}
                </div>
                <div className="absolute left-1/2 top-[3.75rem] flex -translate-x-1/2 gap-2">
                  <QualityChip label="One face" ready={faceStatus === "ready"} warning={faceStatus !== "loading" && faceStatus !== "ready"} />
                  <QualityChip label="Plain light wall" ready={backgroundStatus === "white"} warning={backgroundStatus === "not_white" || backgroundStatus === "not_plain"} />
                </div>
              </div>
            )}
            {isProcessing && (
              <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-3 bg-white/90 px-6 text-center text-slate-900 backdrop-blur-sm">
                <Loader2 className="h-9 w-9 animate-spin text-blue-600" />
                <p className="text-sm font-medium">Saving your original camera photo</p>
              </div>
            )}
          </>
        )}
        <canvas ref={captureCanvasRef} className="hidden" />
        <canvas ref={analysisCanvasRef} className="hidden" />
      </main>

      {!cameraError && (
        <footer className="z-10 flex min-h-[8.75rem] flex-none items-center justify-center border-t border-slate-200 bg-white px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-3 shadow-[0_-8px_24px_rgba(15,23,42,0.08)]">
          {capturedPreview ? (
            <div className="flex w-full max-w-md flex-col gap-3 sm:flex-row">
              <Button variant="outline" size="lg" onClick={retake} className="flex-1 border-slate-300 bg-white text-slate-700 hover:bg-slate-50">
                <RefreshCcw className="mr-2 h-4 w-4" /> Retake
              </Button>
              <Button size="lg" onClick={() => capturedFile && onCapture(capturedFile)} className="flex-1 bg-blue-600 hover:bg-blue-700">
                <Check className="mr-2 h-4 w-4" /> Use Selfie
              </Button>
            </div>
          ) : (
            <div className="grid w-full max-w-sm grid-cols-[1fr_auto_1fr] items-center gap-6">
              <button
                type="button"
                onClick={toggleCamera}
                disabled={!isCameraReady || isProcessing}
                aria-label={`Switch to ${facingMode === "user" ? "back" : "front"} camera`}
                className="justify-self-end rounded-full border border-slate-200 bg-slate-50 p-3 text-slate-700 shadow-sm transition-colors hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700 disabled:opacity-40"
              >
                <RefreshCcw className="h-6 w-6" />
              </button>
              <div className="flex flex-col items-center gap-2 text-center">
                <button
                  type="button"
                  onClick={() => void takePhoto()}
                  disabled={!isCameraReady || isProcessing || !isDetectorReady || !ready}
                  aria-label="Capture selfie manually"
                  className="flex h-[4.5rem] w-[4.5rem] items-center justify-center rounded-full border-4 border-white bg-blue-600 shadow-lg ring-2 ring-blue-600 transition-transform active:scale-95 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:ring-slate-300 disabled:opacity-60"
                >
                  <span className="h-14 w-14 rounded-full border border-white/70" />
                </button>
                <p className="w-40 text-xs leading-4 text-slate-500">{ready ? "Auto-captures after 2 seconds" : "Capture unlocks when both checks pass"}</p>
              </div>
              <div className="justify-self-start">
                {modelError && (
                  <button type="button" onClick={retryChecks} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50">
                    Retry checks
                  </button>
                )}
              </div>
            </div>
          )}
        </footer>
      )}
    </div>
  );
}

function QualityChip({ label, ready, warning }: { label: string; ready: boolean; warning: boolean }) {
  const tone = ready
    ? "border-emerald-300 bg-emerald-50/95 text-emerald-700"
    : warning
      ? "border-amber-300 bg-amber-50/95 text-amber-700"
      : "border-slate-200 bg-white/90 text-slate-600";
  return <span className={`whitespace-nowrap rounded-full border px-3 py-1.5 text-xs font-medium shadow-sm backdrop-blur ${tone}`}>{label}</span>;
}

function faceStatusMessage(status: FaceStatus): string {
  switch (status) {
    case "loading": return "Preparing live photo checks...";
    case "no_face": return "Place one face inside the guide";
    case "multiple": return "Only one person should be visible";
    case "too_far": return "Move closer - your face is too small";
    case "too_close": return "Move back slightly";
    case "off_center": return "Center your head inside the guide";
    case "ready": return "Checking the background...";
    case "unavailable": return "Live checks unavailable - retry to continue";
  }
}

function classifyFace(detections: Detection[], video: HTMLVideoElement, guide: HTMLDivElement): FaceStatus {
  if (detections.length === 0) return "no_face";
  if (detections.length > 1) return "multiple";

  const box = detections[0].boundingBox;
  const crop = getVisibleGuideCrop(video, guide);
  const relativeWidth = (box.width * video.videoWidth) / crop.width;
  const relativeHeight = (box.height * video.videoHeight) / crop.height;
  const relativeX = (box.xCenter * video.videoWidth - crop.left) / crop.width;
  const relativeY = (box.yCenter * video.videoHeight - crop.top) / crop.height;

  if (!isVisaSelfieFaceLargeEnough(relativeWidth, relativeHeight)) return "too_far";
  if (relativeHeight > 0.74 || relativeWidth > 0.72) return "too_close";
  if (Math.abs(relativeX - 0.5) > 0.11 || relativeY < 0.27 || relativeY > 0.52) return "off_center";
  return "ready";
}

function analyzeWhiteBackground(video: HTMLVideoElement, guide: HTMLDivElement, canvas: HTMLCanvasElement): ResolvedBackgroundStatus {
  const crop = getVisibleGuideCrop(video, guide);
  canvas.width = ANALYSIS_WIDTH;
  canvas.height = ANALYSIS_HEIGHT;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return "not_white";

  context.drawImage(video, crop.left, crop.top, crop.width, crop.height, 0, 0, ANALYSIS_WIDTH, ANALYSIS_HEIGHT);
  const pixels = context.getImageData(0, 0, ANALYSIS_WIDTH, ANALYSIS_HEIGHT).data;
  const result = evaluateWhiteBackground(pixels, ANALYSIS_WIDTH, ANALYSIS_HEIGHT);
  if (result.isWhite) return "white";
  return result.failureReason === "not_plain" ? "not_plain" : "not_white";
}

function stabilizeBackgroundStatus(
  sample: ResolvedBackgroundStatus,
  samples: ResolvedBackgroundStatus[],
): BackgroundStatus {
  samples.push(sample);
  if (samples.length > 4) samples.shift();
  if (samples.length < 4) return "checking";

  const statuses: ResolvedBackgroundStatus[] = ["white", "not_white", "not_plain"];
  return statuses.find((status) => samples.filter((value) => value === status).length >= 3)
    ?? "checking";
}

function canvasToJpeg(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (value) => value ? resolve(value) : reject(new Error("Could not save the selfie.")),
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

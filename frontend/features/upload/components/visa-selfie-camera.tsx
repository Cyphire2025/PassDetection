"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Image from "next/image";
import { AlertTriangle, Check, Loader2, RefreshCcw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Detection } from "@mediapipe/face_detection";
import type { Results as SegmentationResults } from "@mediapipe/selfie_segmentation";

interface VisaSelfieCameraProps {
  onCapture: (file: File) => void;
  onCancel: () => void;
}

type FaceStatus = "loading" | "no_face" | "multiple" | "too_far" | "too_close" | "off_center" | "ready" | "unavailable";

const OUTPUT_WIDTH = 826;
const OUTPUT_HEIGHT = 1062;
const STABLE_CAPTURE_MS = 2_000;
const ANALYSIS_INTERVAL_MS = 180;

export function VisaSelfieCamera({ onCapture, onCancel }: VisaSelfieCameraProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const guideRef = useRef<HTMLDivElement>(null);
  const captureCanvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const detectorRef = useRef<import("@mediapipe/face_detection").FaceDetection | null>(null);
  const segmenterRef = useRef<import("@mediapipe/selfie_segmentation").SelfieSegmentation | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const lastAnalysisRef = useRef(0);
  const analysisBusyRef = useRef(false);
  const latestDetectionsRef = useRef<Detection[]>([]);
  const stableSinceRef = useRef<number | null>(null);
  const captureStartedRef = useRef(false);

  const [isCameraReady, setIsCameraReady] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [faceStatus, setFaceStatus] = useState<FaceStatus>("loading");
  const [segmentationReady, setSegmentationReady] = useState(false);
  const [modelError, setModelError] = useState<string | null>(null);
  const [initializationAttempt, setInitializationAttempt] = useState(0);
  const [countdown, setCountdown] = useState<number | null>(null);
  const [capturedFile, setCapturedFile] = useState<File | null>(null);
  const [capturedPreview, setCapturedPreview] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingError, setProcessingError] = useState<string | null>(null);

  const stopCamera = useCallback(() => {
    if (animationFrameRef.current !== null) cancelAnimationFrame(animationFrameRef.current);
    animationFrameRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const classifyFace = useCallback((detections: Detection[], video: HTMLVideoElement, guide: HTMLDivElement): FaceStatus => {
    if (detections.length === 0) return "no_face";
    if (detections.length > 1) return "multiple";

    const box = detections[0].boundingBox;
    const crop = getVisibleGuideCrop(video, guide);
    const relativeWidth = (box.width * video.videoWidth) / crop.width;
    const relativeHeight = (box.height * video.videoHeight) / crop.height;
    const relativeX = ((box.xCenter * video.videoWidth) - crop.left) / crop.width;
    const relativeY = ((box.yCenter * video.videoHeight) - crop.top) / crop.height;

    if (relativeHeight < 0.48 || relativeWidth < 0.36) return "too_far";
    if (relativeHeight > 0.78 || relativeWidth > 0.76) return "too_close";
    if (Math.abs(relativeX - 0.5) > 0.1 || Math.abs(relativeY - 0.45) > 0.12) return "off_center";
    return "ready";
  }, []);

  const removeBackground = useCallback(async (source: HTMLCanvasElement): Promise<File> => {
    const segmenter = segmenterRef.current;
    if (!segmenter) throw new Error("Background processor is still loading. Please wait a moment and retry.");

    const results = await new Promise<SegmentationResults>((resolve, reject) => {
      const timer = window.setTimeout(() => reject(new Error("Background processing timed out. Please retry.")), 12_000);
      segmenter.onResults((value) => {
        window.clearTimeout(timer);
        resolve(value);
      });
      void segmenter.send({ image: source }).catch((error) => {
        window.clearTimeout(timer);
        reject(error);
      });
    });

    const output = document.createElement("canvas");
    output.width = OUTPUT_WIDTH;
    output.height = OUTPUT_HEIGHT;
    const context = output.getContext("2d");
    if (!context) throw new Error("This browser cannot process the selfie image.");

    context.save();
    context.filter = "blur(1.2px)";
    context.drawImage(results.segmentationMask, 0, 0, OUTPUT_WIDTH, OUTPUT_HEIGHT);
    context.filter = "none";
    context.globalCompositeOperation = "source-in";
    context.drawImage(source, 0, 0, OUTPUT_WIDTH, OUTPUT_HEIGHT);
    context.globalCompositeOperation = "destination-over";
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, OUTPUT_WIDTH, OUTPUT_HEIGHT);
    context.restore();

    const blob = await new Promise<Blob>((resolve, reject) => {
      output.toBlob((value) => value ? resolve(value) : reject(new Error("Could not save the processed selfie.")), "image/jpeg", 0.94);
    });
    return new File([blob], `visa-selfie-${Date.now()}.jpg`, { type: "image/jpeg", lastModified: Date.now() });
  }, []);

  const takePhoto = useCallback(async () => {
    const video = videoRef.current;
    const guide = guideRef.current;
    const canvas = captureCanvasRef.current;
    if (!video || !guide || !canvas || !isCameraReady || captureStartedRef.current) return;

    captureStartedRef.current = true;
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

      context.drawImage(video, crop.left, crop.top, crop.width, crop.height, 0, 0, OUTPUT_WIDTH, OUTPUT_HEIGHT);

      const file = await removeBackground(canvas);
      setCapturedFile(file);
      setCapturedPreview(URL.createObjectURL(file));
    } catch (error) {
      setProcessingError(error instanceof Error ? error.message : "The selfie could not be processed. Please retry.");
    } finally {
      setIsProcessing(false);
      captureStartedRef.current = false;
    }
  }, [isCameraReady, removeBackground]);

  useEffect(() => {
    let disposed = false;

    async function initialize() {
      setModelError(null);
      setSegmentationReady(false);
      setFaceStatus("loading");
      setIsCameraReady(false);
      latestDetectionsRef.current = [];
      analysisBusyRef.current = false;
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        setCameraError("Camera access requires HTTPS, or localhost during development.");
        return;
      }

      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 1280 } },
          audio: false,
        });
        if (disposed) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play().catch(() => undefined);
        }
      } catch (error) {
        setCameraError(error instanceof DOMException && error.name === "NotAllowedError"
          ? "Camera permission was blocked. Allow camera access and try again."
          : "The front camera could not be started on this device.");
        return;
      }

      try {
        const [{ FaceDetection }, { SelfieSegmentation }] = await Promise.all([
          import("@mediapipe/face_detection"),
          import("@mediapipe/selfie_segmentation"),
        ]);
        if (disposed) return;

        const segmenter = new SelfieSegmentation({ locateFile: (file) => `/mediapipe/selfie_segmentation/${file}` });
        segmenter.setOptions({ modelSelection: 0, selfieMode: true });
        segmenterRef.current = segmenter;
        await segmenter.initialize();
        if (disposed) return;
        setSegmentationReady(true);

        try {
          const detector = new FaceDetection({ locateFile: (file) => `/mediapipe/face_detection/${file}` });
          detector.setOptions({ model: "short", selfieMode: true, minDetectionConfidence: 0.72 });
          detector.onResults((results) => {
            latestDetectionsRef.current = results.detections;
            analysisBusyRef.current = false;
          });
          await detector.initialize();
          if (disposed) {
            await detector.close();
            return;
          }
          detectorRef.current = detector;
        } catch (error) {
          console.error("VISA selfie face detection initialization failed", error);
          setFaceStatus("unavailable");
        }
      } catch (error) {
        console.error("VISA selfie ML initialization failed", error);
        setFaceStatus("unavailable");
        setModelError("The white-background processor could not start. Check your connection and retry.");
      }
    }

    void initialize();
    return () => {
      disposed = true;
      stopCamera();
      void detectorRef.current?.close();
      void segmenterRef.current?.close();
      detectorRef.current = null;
      segmenterRef.current = null;
    };
  }, [initializationAttempt, stopCamera]);

  useEffect(() => {
    if (!isCameraReady || capturedPreview || cameraError) return;

    const analyze = (now: number) => {
      const detector = detectorRef.current;
      const video = videoRef.current;
      if (detector && video && !analysisBusyRef.current && now - lastAnalysisRef.current >= ANALYSIS_INTERVAL_MS) {
        lastAnalysisRef.current = now;
        analysisBusyRef.current = true;
        void detector.send({ image: video }).catch(() => {
          analysisBusyRef.current = false;
          setFaceStatus("unavailable");
        });
      }

      if (detector && video && guideRef.current) {
        const status = classifyFace(latestDetectionsRef.current, video, guideRef.current);
        setFaceStatus(status);
        if (status === "ready" && !captureStartedRef.current) {
          const stableSince = stableSinceRef.current ?? now;
          stableSinceRef.current = stableSince;
          const remaining = STABLE_CAPTURE_MS - (now - stableSince);
          setCountdown(Math.max(1, Math.ceil(remaining / 1000)));
          if (remaining <= 0) void takePhoto();
        } else {
          stableSinceRef.current = null;
          setCountdown(null);
        }
      }
      animationFrameRef.current = requestAnimationFrame(analyze);
    };

    animationFrameRef.current = requestAnimationFrame(analyze);
    return () => {
      if (animationFrameRef.current !== null) cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    };
  }, [cameraError, capturedPreview, classifyFace, isCameraReady, takePhoto]);

  useEffect(() => {
    return () => {
      if (capturedPreview) URL.revokeObjectURL(capturedPreview);
    };
  }, [capturedPreview]);

  const retake = () => {
    setCapturedPreview(null);
    setCapturedFile(null);
    setProcessingError(null);
    stableSinceRef.current = null;
    captureStartedRef.current = false;
  };

  const close = () => {
    stopCamera();
    onCancel();
  };

  const guidance = processingError
    ? processingError
    : modelError
      ? modelError
    : isProcessing
      ? "Removing the background and applying a clean white backdrop..."
      : countdown
        ? `Hold still — capturing in ${countdown}`
        : faceStatusMessage(faceStatus);

  const ready = faceStatus === "ready";

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-slate-950 text-white">
      <header className="flex h-16 items-center justify-between px-4 pt-[max(0.25rem,env(safe-area-inset-top))]">
        <button type="button" onClick={close} aria-label="Close selfie camera" className="rounded-full p-2 text-white/80 hover:bg-white/10 hover:text-white">
          <X className="h-6 w-6" />
        </button>
        <div className="text-center">
          <h2 className="text-base font-semibold">VISA Selfie Photo</h2>
          <p className="text-xs text-slate-400">White background applied automatically</p>
        </div>
        <div className="w-10" aria-hidden="true" />
      </header>

      <main className="relative flex flex-1 items-center justify-center overflow-hidden bg-black">
        {cameraError ? (
          <div className="mx-6 max-w-md rounded-2xl border border-amber-400/30 bg-slate-900 p-6 text-center">
            <AlertTriangle className="mx-auto mb-4 h-10 w-10 text-amber-400" />
            <h3 className="mb-2 text-lg font-semibold">Camera unavailable</h3>
            <p className="mb-6 text-sm leading-6 text-slate-300">{cameraError}</p>
            <Button onClick={close} className="w-full">Back</Button>
          </div>
        ) : (
          <>
            <video
              ref={videoRef}
              autoPlay
              muted
              playsInline
              onLoadedData={() => setIsCameraReady(true)}
              className={`h-full w-full scale-x-[-1] object-cover ${capturedPreview ? "opacity-0" : "opacity-100"}`}
            />
            {capturedPreview ? (
              <Image src={capturedPreview} alt="Processed VISA selfie with white background" fill unoptimized className="object-contain" />
            ) : (
              <div className="pointer-events-none absolute inset-0">
                <div ref={guideRef} className="absolute left-1/2 top-1/2 aspect-[35/45] w-[min(88vw,56vh,32rem)] -translate-x-1/2 -translate-y-1/2">
                  <div className={`absolute inset-0 rounded-3xl border-2 shadow-[0_0_0_9999px_rgba(2,6,23,0.5)] transition-colors ${ready ? "border-emerald-400" : "border-white/65"}`} />
                  <div className={`absolute left-1/2 top-[47%] h-[76%] w-[72%] -translate-x-1/2 -translate-y-1/2 rounded-[50%] border-2 border-dashed transition-colors ${ready ? "border-emerald-300" : "border-white/70"}`} />
                  <div className="absolute bottom-[7%] left-1/2 h-[26%] w-[82%] -translate-x-1/2 rounded-t-[50%] border-x-2 border-t-2 border-dashed border-white/50" />
                </div>
                <div className={`absolute left-1/2 top-4 w-max max-w-[92%] -translate-x-1/2 rounded-full px-4 py-2 text-center text-sm font-medium shadow-lg backdrop-blur ${processingError ? "bg-red-600" : ready ? "bg-emerald-500" : "bg-black/60"}`}>
                  {guidance}
                </div>
              </div>
            )}
            {isProcessing && (
              <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-3 bg-slate-950/85 px-6 text-center backdrop-blur-sm">
                <Loader2 className="h-9 w-9 animate-spin text-blue-400" />
                <p className="text-sm font-medium">Creating your VISA-ready white-background photo</p>
              </div>
            )}
          </>
        )}
        <canvas ref={captureCanvasRef} className="hidden" />
      </main>

      {!cameraError && (
        <footer className="flex min-h-28 items-center justify-center bg-slate-950/90 px-4 py-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
          {capturedPreview ? (
            <div className="flex w-full max-w-md flex-col gap-3 sm:flex-row">
              <Button variant="outline" size="lg" onClick={retake} className="flex-1 border-white/20 bg-white/10 text-white hover:bg-white/20">
                <RefreshCcw className="mr-2 h-4 w-4" /> Retake
              </Button>
              <Button size="lg" onClick={() => capturedFile && onCapture(capturedFile)} className="flex-1 bg-blue-600 hover:bg-blue-500">
                <Check className="mr-2 h-4 w-4" /> Use Selfie
              </Button>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-2 text-center">
              <button
                type="button"
                onClick={() => void takePhoto()}
                disabled={!isCameraReady || isProcessing || !segmentationReady}
                aria-label="Capture selfie manually"
                className="flex h-20 w-20 items-center justify-center rounded-full border-4 border-slate-950 bg-white ring-2 ring-white disabled:opacity-40"
              >
                <span className="h-16 w-16 rounded-full border border-slate-200" />
              </button>
              {modelError ? (
                <button type="button" onClick={() => setInitializationAttempt((value) => value + 1)} className="rounded-lg border border-white/20 px-4 py-2 text-xs font-semibold text-white hover:bg-white/10">
                  Retry photo processing
                </button>
              ) : (
                <p className="text-xs text-slate-400">{faceStatus === "unavailable" ? "Automatic framing unavailable — capture manually" : "Auto-captures after 2 seconds in position"}</p>
              )}
            </div>
          )}
        </footer>
      )}
    </div>
  );
}

function faceStatusMessage(status: FaceStatus): string {
  switch (status) {
    case "loading": return "Preparing secure face detection...";
    case "no_face": return "Place your face inside the oval";
    case "multiple": return "Only one person should be visible";
    case "too_far": return "Move closer — your face is too small";
    case "too_close": return "Move back slightly";
    case "off_center": return "Center your face inside the oval";
    case "ready": return "Perfect position — hold still";
    case "unavailable": return "Automatic framing unavailable — use the capture button";
  }
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

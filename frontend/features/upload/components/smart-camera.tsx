"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Image from "next/image";
import { AlertTriangle, X, Check, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { usePassportFrameDetection } from "../hooks/use-passport-frame-detection";
import { usePassportBlurDetection } from "../hooks/use-passport-blur-detection";
import { usePassportLightingDetection } from "../hooks/use-passport-lighting-detection";
import { usePassportGlareDetection } from "../hooks/use-passport-glare-detection";
import { useStableTelemetryReason } from "../hooks/use-stable-telemetry-reason";
import { normalizePassportCanvasCapture } from "../services/passport-perspective-correction";
import {
  passportScannerRejectionReason,
  type PassportScannerRejectionReason,
} from "../services/public-flow-telemetry";
import type {
  PassportFrameStatus,
  PassportPageSide,
} from "../services/passport-frame-detector";

interface SmartCameraProps {
  onCapture: (file: File) => void;
  onCancel: () => void;
  pageSide: PassportPageSide;
  allowFileFallback?: boolean;
  onTelemetryReason?: (reason: PassportScannerRejectionReason) => void;
}

export function SmartCamera({
  onCapture,
  onCancel,
  pageSide,
  allowFileFallback = true,
  onTelemetryReason = () => undefined,
}: SmartCameraProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const guideRef = useRef<HTMLDivElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const analysisCanvasRef = useRef<HTMLCanvasElement>(null);
  const blurCanvasRef = useRef<HTMLCanvasElement>(null);
  const lightingCanvasRef = useRef<HTMLCanvasElement>(null);
  const glareCanvasRef = useRef<HTMLCanvasElement>(null);
  const [cameraRestartGeneration, setCameraRestartGeneration] = useState(0);
  const [capturedImage, setCapturedImage] = useState<string | null>(null);
  const [capturedFile, setCapturedFile] = useState<File | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isReady, setIsReady] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [failureReason, setFailureReason] = useState<
    "camera_unavailable" | "crop_validation_failed" | null
  >(null);
  const [isProcessingCapture, setIsProcessingCapture] = useState(false);
  const visibilityPausedRef = useRef(false);
  const mountedRef = useRef(true);

  const {
    isDetected: isPassportDetected,
    status: passportFrameStatus,
    isCriticalZoneObstructed,
    hasDocumentCandidate,
    detectionSequence: passportDetectionSequence,
  } = usePassportFrameDetection({
    videoRef,
    canvasRef: analysisCanvasRef,
    guideRef,
    enabled: isReady && !capturedImage && !cameraError,
    pageSide,
    resetKey: cameraRestartGeneration,
  });
  const qualityResetKey = `${cameraRestartGeneration}:${passportDetectionSequence}`;

  const { status: blurStatus, isSharp } = usePassportBlurDetection({
    videoRef,
    canvasRef: blurCanvasRef,
    guideRef,
    enabled: isReady && isPassportDetected && !capturedImage && !cameraError,
    resetKey: qualityResetKey,
  });

  const { status: lightingStatus, isWellLit } = usePassportLightingDetection({
    videoRef,
    canvasRef: lightingCanvasRef,
    guideRef,
    enabled: isReady && isPassportDetected && !capturedImage && !cameraError,
    resetKey: qualityResetKey,
  });
  const { status: glareStatus, hasGlare } = usePassportGlareDetection({
    videoRef,
    canvasRef: glareCanvasRef,
    guideRef,
    enabled: isReady && isPassportDetected && !capturedImage && !cameraError,
    resetKey: qualityResetKey,
  });

  const isCaptureReady = isPassportDetected
    && isSharp
    && isWellLit
    && glareStatus === "clear"
    && !hasGlare
    && !isProcessingCapture;

  const telemetryReason = passportScannerRejectionReason({
    failureReason,
    frameStatus: passportFrameStatus,
    passportDetected: isPassportDetected,
    glareStatus,
    lightingStatus,
    blurStatus,
  });
  useStableTelemetryReason(telemetryReason, onTelemetryReason);

  const guideToneClass = isCaptureReady
    ? "border-emerald-400"
    : hasDocumentCandidate
      ? "border-amber-400"
      : "border-white/60";

  const statusBannerClass = isCaptureReady
    ? "bg-emerald-500 text-white"
    : hasDocumentCandidate
      ? "bg-amber-500 text-slate-950"
      : "bg-black/55 text-white/90";

  const guidanceMessage = isProcessingCapture
    ? `Straightening and saving the passport ${pageSide} page`
    : isCaptureReady
      ? "All checks passed - tap the shutter button to capture"
    : isCriticalZoneObstructed
      ? "Remove fingers from the passport photo, printed details, and MRZ"
    : !isPassportDetected
    ? passportFrameGuidance(passportFrameStatus, pageSide)
    : glareStatus === "checking"
      ? "Checking surface glare"
    : glareStatus === "glare"
      ? "Tilt the passport to remove screen glare"
    : lightingStatus === "checking"
      ? "Checking lighting quality"
    : hasGlare
      ? "Tilt the passport to remove screen glare"
      : lightingStatus === "too_dark"
      ? "Move into brighter, even lighting"
      : lightingStatus === "too_bright"
        ? "Reduce harsh light on the passport"
        : blurStatus !== "sharp"
          ? "Hold steady - image is blurry"
          : "Passport detected - image is ready";

  const stopCamera = useCallback(() => {
    if (videoRef.current) {
      videoRef.current.pause();
      videoRef.current.srcObject = null;
    }
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    let disposed = false;

    async function startCamera() {
      setIsLoading(true);
      setIsReady(false);
      setCameraError(null);
      setFailureReason(null);

      try {
        if (document.visibilityState === "hidden") {
          visibilityPausedRef.current = true;
          return;
        }
        if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
          setFailureReason("camera_unavailable");
          setCameraError(
            "This custom passport scanner needs a secure camera session. Open the upload link over HTTPS to use the live detection frame, glare, blur, and lighting checks.",
          );
          return;
        }

        stopCamera();

        const mediaStream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: "environment" },
            width: { ideal: 1920 },
            height: { ideal: 1080 },
          },
          audio: false,
        });

        if (disposed) {
          mediaStream.getTracks().forEach((track) => track.stop());
          return;
        }
        if (isPageHidden()) {
          mediaStream.getTracks().forEach((track) => track.stop());
          visibilityPausedRef.current = true;
          return;
        }

        streamRef.current = mediaStream;
        if (videoRef.current) {
          videoRef.current.srcObject = mediaStream;
          await videoRef.current.play().catch(() => undefined);
        }
      } catch (error) {
        if (disposed) return;
        setFailureReason("camera_unavailable");
        setCameraError(
          error instanceof DOMException && error.name === "NotAllowedError"
            ? "Camera access was blocked. Allow camera permission in your browser and try again."
            : allowFileFallback
              ? "The camera could not be started. Open the link over HTTPS or go back and upload a photo instead."
              : "The camera could not be started. This group requires live scanning, so open the link over HTTPS and allow camera access.",
        );
      } finally {
        if (!disposed) setIsLoading(false);
      }
    }

    void startCamera();

    return () => {
      disposed = true;
      stopCamera();
    };
  }, [allowFileFallback, cameraRestartGeneration, stopCamera]);

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        if (capturedImage) return;
        visibilityPausedRef.current = true;
        stopCamera();
        setIsReady(false);
        setIsLoading(false);
        return;
      }
      if (!visibilityPausedRef.current || capturedImage) return;
      visibilityPausedRef.current = false;
      setIsLoading(true);
      setCameraRestartGeneration((generation) => generation + 1);
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [capturedImage, stopCamera]);

  const takePhoto = useCallback(async () => {
    if (
      !videoRef.current
      || !canvasRef.current
      || !isReady
      || !isCaptureReady
    ) return;

    const video = videoRef.current;
    const canvas = canvasRef.current;
    // Keep minimal context around every side of the guide so the shared
    // normalizer has enough boundary pixels for perspective rectification.
    const crop = addCaptureMargin(getVisibleGuideCrop(video, guideRef.current), video.videoWidth, video.videoHeight);
    const cropWidth = Math.max(1, Math.round(crop.width));
    const cropHeight = Math.max(1, Math.round(crop.height));

    canvas.width = cropWidth;
    canvas.height = cropHeight;

    const context = canvas.getContext("2d");
    if (context) {
      setIsProcessingCapture(true);

      try {
        context.drawImage(
          video,
          crop.left,
          crop.top,
          cropWidth,
          cropHeight,
          0,
          0,
          cropWidth,
          cropHeight,
        );

        const normalized = await normalizePassportCanvasCapture(
          canvas,
          `passport-${pageSide}-capture.jpg`,
          pageSide,
        );
        if (!mountedRef.current) return;
        setCapturedFile(normalized.file);
        setCapturedImage(normalized.previewDataUrl);
        setFailureReason(null);
        stopCamera();
      } catch {
        stopCamera();
        if (mountedRef.current) {
          setFailureReason("crop_validation_failed");
          setCameraError(
            `The passport ${pageSide} page could not be prepared. Try the camera again or go back and choose another capture method.`,
          );
        }
      } finally {
        if (mountedRef.current) setIsProcessingCapture(false);
      }
    }
  }, [
    isCaptureReady,
    isReady,
    pageSide,
    stopCamera,
  ]);

  const restartCamera = () => {
    stopCamera();
    setCameraError(null);
    setFailureReason(null);
    setCapturedImage(null);
    setCapturedFile(null);
    setIsReady(false);
    setCameraRestartGeneration((generation) => generation + 1);
  };

  const retake = () => {
    setCapturedImage(null);
    setCapturedFile(null);
    setIsProcessingCapture(false);
    setIsReady(false);

    setCameraRestartGeneration((generation) => generation + 1);
  };

  const confirm = () => {
    if (!capturedFile) return;
    stopCamera();
    onCapture(capturedFile);
  };

  const close = () => {
    stopCamera();
    onCancel();
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="passport-camera-title"
      className="fixed inset-0 z-50 flex flex-col bg-slate-950 text-white"
    >
      <div className="flex h-16 items-center justify-between px-4 pt-[max(0.25rem,env(safe-area-inset-top))]">
        <button
          type="button"
          onClick={close}
          aria-label="Close camera"
          className="rounded-full p-2 text-white/80 transition-colors hover:bg-white/10 hover:text-white"
        >
          <X className="h-6 w-6" />
        </button>
        <h2 id="passport-camera-title" className="text-lg font-semibold tracking-tight">
          Passport {pageSide === "front" ? "Front" : "Back"} Scan
        </h2>
        <div className="w-10" aria-hidden="true" />
      </div>

      <div className="relative flex flex-1 flex-col items-center justify-center overflow-hidden bg-black">
        {(isLoading || isProcessingCapture) && !capturedImage && (
          <div
            role="status"
            aria-live="polite"
            className="absolute inset-0 z-10 flex items-center justify-center bg-slate-950"
          >
            <Loader2 className="h-8 w-8 animate-spin text-blue-500" aria-hidden="true" />
            <span className="sr-only">
              {isProcessingCapture ? "Preparing passport image" : "Starting camera"}
            </span>
          </div>
        )}

        {cameraError ? (
          <div
            role="alert"
            className="mx-6 max-w-md rounded-2xl border border-amber-400/30 bg-slate-900 p-6 text-center shadow-2xl"
          >
            <AlertTriangle className="mx-auto mb-4 h-10 w-10 text-amber-400" aria-hidden="true" />
            <h3 className="mb-2 text-lg font-semibold">
              {failureReason === "crop_validation_failed"
                ? "Passport image needs another try"
                : "Camera unavailable"}
            </h3>
            <p className="mb-6 text-sm leading-6 text-slate-300">{cameraError}</p>
            <div className="flex flex-col gap-3">
              <Button onClick={restartCamera} className="w-full">
                Try Camera Again
              </Button>
              <Button variant="outline" onClick={close} className="w-full border-white/20 bg-white/10 text-white hover:bg-white/20">
                Back
              </Button>
              <p className="text-xs text-slate-400">
                The custom scanner works only when the page is opened from a secure origin.
              </p>
            </div>
          </div>
        ) : (
          <>
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              onLoadedData={() => setIsReady(true)}
              className={`h-full w-full object-cover ${capturedImage ? "opacity-0" : "opacity-100"}`}
            />

            {capturedImage ? (
              <Image
                src={capturedImage}
                alt={`Captured passport ${pageSide} page`}
                fill
                unoptimized
                className="object-contain"
              />
            ) : (
              <div className="pointer-events-none absolute inset-0">
                <div
                  ref={guideRef}
                  className="absolute left-1/2 top-1/2 h-auto w-[min(88vw,34rem)] -translate-x-1/2 -translate-y-1/2 aspect-[1.42/1] max-h-[56vh]"
                >
                  <div className={`absolute inset-0 rounded-[22px] border-2 transition-colors shadow-[0_0_0_9999px_rgba(2,6,23,0.44)] ${guideToneClass}`}>
                    <div className="absolute -left-1 -top-1 h-8 w-8 rounded-tl-lg border-l-4 border-t-4 border-blue-500"></div>
                    <div className="absolute -right-1 -top-1 h-8 w-8 rounded-tr-lg border-r-4 border-t-4 border-blue-500"></div>
                    <div className="absolute -bottom-1 -left-1 h-8 w-8 rounded-bl-lg border-b-4 border-l-4 border-blue-500"></div>
                    <div className="absolute -bottom-1 -right-1 h-8 w-8 rounded-br-lg border-b-4 border-r-4 border-blue-500"></div>
                  </div>
                </div>

                <div
                  role="status"
                  aria-live="polite"
                  aria-atomic="true"
                  className={`absolute left-1/2 top-5 w-[min(92%,28rem)] -translate-x-1/2 rounded-2xl px-4 py-2.5 text-center text-sm font-medium shadow-lg backdrop-blur ${statusBannerClass}`}
                >
                  <div>{guidanceMessage}</div>
                </div>

              </div>
            )}
          </>
        )}

        <canvas ref={canvasRef} className="hidden" />
        <canvas ref={analysisCanvasRef} className="hidden" />
        <canvas ref={blurCanvasRef} className="hidden" />
        <canvas ref={lightingCanvasRef} className="hidden" />
        <canvas ref={glareCanvasRef} className="hidden" />
      </div>

      {!cameraError && (
        <div className="flex min-h-28 items-center justify-center gap-8 bg-slate-950/85 px-4 py-4 pb-[max(1rem,env(safe-area-inset-bottom))] backdrop-blur-md sm:min-h-32 sm:gap-10 sm:px-6 sm:py-6">
          {capturedImage ? (
            <div className="mx-auto flex w-full max-w-md flex-col gap-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
              <Button
                variant="outline"
                size="lg"
                onClick={retake}
                className="flex-1 border-white/20 bg-white/10 text-white hover:bg-white/20"
              >
                Retake
              </Button>
              <Button
                size="lg"
                onClick={confirm}
                className="flex-1 bg-blue-600 font-medium text-white hover:bg-blue-500"
              >
                <Check className="mr-2 h-4 w-4" /> Use Photo
              </Button>
            </div>
          ) : (
            <>
              <div className="h-12 w-12" aria-hidden="true" />
              <button
                type="button"
                onClick={() => void takePhoto()}
                disabled={!isCaptureReady}
                aria-label={
                  isCaptureReady
                    ? "Capture passport page"
                    : "Passport capture is unavailable until every check passes"
                }
                className="flex h-20 w-20 items-center justify-center rounded-full border-4 border-slate-950 bg-white ring-2 ring-white transition-transform hover:scale-95 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <div className="h-16 w-16 rounded-full border border-slate-200 bg-white"></div>
              </button>
              <div className="h-12 w-12" aria-hidden="true" />
            </>
          )}
        </div>
      )}
    </div>
  );
}

interface CropBounds {
  left: number;
  top: number;
  width: number;
  height: number;
}

function getVisibleGuideCrop(video: HTMLVideoElement, guide: HTMLDivElement | null): CropBounds {
  const videoWidth = video.videoWidth;
  const videoHeight = video.videoHeight;

  if (!guide || videoWidth <= 0 || videoHeight <= 0) {
    return {
      left: 0,
      top: 0,
      width: videoWidth || 1,
      height: videoHeight || 1,
    };
  }

  const videoRect = video.getBoundingClientRect();
  const guideRect = guide.getBoundingClientRect();
  const scale = Math.max(videoRect.width / videoWidth, videoRect.height / videoHeight);
  const renderedWidth = videoWidth * scale;
  const renderedHeight = videoHeight * scale;
  const offsetX = (renderedWidth - videoRect.width) / 2;
  const offsetY = (renderedHeight - videoRect.height) / 2;

  const crop = {
    left: (guideRect.left - videoRect.left + offsetX) / scale,
    top: (guideRect.top - videoRect.top + offsetY) / scale,
    width: guideRect.width / scale,
    height: guideRect.height / scale,
  };

  return clampCrop(crop, videoWidth, videoHeight);
}

function clampCrop(crop: CropBounds, maxWidth: number, maxHeight: number): CropBounds {
  const left = Math.max(0, Math.min(maxWidth - 1, crop.left));
  const top = Math.max(0, Math.min(maxHeight - 1, crop.top));
  const right = Math.max(left + 1, Math.min(maxWidth, crop.left + crop.width));
  const bottom = Math.max(top + 1, Math.min(maxHeight, crop.top + crop.height));

  return {
    left,
    top,
    width: right - left,
    height: bottom - top,
  };
}

function addCaptureMargin(crop: CropBounds, maxWidth: number, maxHeight: number): CropBounds {
  const horizontalMargin = crop.width * 0.02;
  const verticalMargin = crop.height * 0.02;
  return clampCrop(
    {
      left: crop.left - horizontalMargin,
      top: crop.top - verticalMargin,
      width: crop.width + horizontalMargin * 2,
      height: crop.height + verticalMargin * 2,
    },
    maxWidth,
    maxHeight,
  );
}

function passportFrameGuidance(
  status: PassportFrameStatus,
  pageSide: PassportPageSide,
): string {
  switch (status) {
    case "checking":
      return "Hold steady while the passport page is checked";
    case "no_document":
      return pageSide === "front"
        ? "Position the passport information page inside the frame"
        : "Position the passport back page inside the frame";
    case "incomplete_document":
      return "Show all four page corners inside the frame";
    case "too_small":
      return "Move closer while keeping all four corners visible";
    case "sideways":
    case "upside_down":
    case "excessive_skew":
      return "Hold the passport upright and align it inside the frame";
    case "multiple_documents":
      return "Show only one passport page inside the frame";
    case "screen_or_book":
      return pageSide === "front"
        ? "Show the physical passport information page, not a screen or book"
        : "Show the physical passport back page, not a screen or book";
    case "missing_mrz":
    case "not_passport_page":
      return pageSide === "front"
        ? "Show the passport information page with the photo and MRZ"
        : "Show the passport back page with its printed details";
    case "ready":
      return "Passport page detected - hold steady";
  }
}

function isPageHidden() {
  return document.visibilityState === "hidden";
}

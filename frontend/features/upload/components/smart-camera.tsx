"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Image from "next/image";
import { AlertTriangle, RefreshCcw, X, Check, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { usePassportFrameDetection } from "../hooks/use-passport-frame-detection";
import { usePassportBlurDetection } from "../hooks/use-passport-blur-detection";
import { usePassportLightingDetection } from "../hooks/use-passport-lighting-detection";
import { usePassportGlareDetection } from "../hooks/use-passport-glare-detection";
import { normalizePassportCanvasCapture } from "../services/passport-perspective-correction";
import type { PassportPageSide } from "../services/passport-frame-detector";
import {
  getEmptyPassportAutoCaptureProgress,
  getPassportAutoCaptureProgress,
  PASSPORT_AUTO_CAPTURE_TICK_MS,
} from "./passport-auto-capture";

interface SmartCameraProps {
  onCapture: (file: File) => void;
  onCancel: () => void;
  pageSide: PassportPageSide;
  allowFileFallback?: boolean;
}

export function SmartCamera({
  onCapture,
  onCancel,
  pageSide,
  allowFileFallback = true,
}: SmartCameraProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const guideRef = useRef<HTMLDivElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const analysisCanvasRef = useRef<HTMLCanvasElement>(null);
  const blurCanvasRef = useRef<HTMLCanvasElement>(null);
  const lightingCanvasRef = useRef<HTMLCanvasElement>(null);
  const glareCanvasRef = useRef<HTMLCanvasElement>(null);
  const [facingMode, setFacingMode] = useState<"environment" | "user">("environment");
  const [cameraRestartGeneration, setCameraRestartGeneration] = useState(0);
  const [capturedImage, setCapturedImage] = useState<string | null>(null);
  const [capturedFile, setCapturedFile] = useState<File | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isReady, setIsReady] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [isProcessingCapture, setIsProcessingCapture] = useState(false);
  const [autoCaptureProgress, setAutoCaptureProgress] = useState(
    getEmptyPassportAutoCaptureProgress,
  );
  const autoCaptureStableSinceRef = useRef<number | null>(null);
  const autoCaptureTimeoutRef = useRef<number | null>(null);
  const autoCaptureIntervalRef = useRef<number | null>(null);
  const mountedRef = useRef(true);

  const { isDetected: isPassportDetected } = usePassportFrameDetection({
    videoRef,
    canvasRef: analysisCanvasRef,
    enabled: isReady && !capturedImage && !cameraError,
    pageSide,
  });

  const { status: blurStatus, isSharp } = usePassportBlurDetection({
    videoRef,
    canvasRef: blurCanvasRef,
    enabled: isReady && isPassportDetected && !capturedImage && !cameraError,
  });

  const { status: lightingStatus, isWellLit } = usePassportLightingDetection({
    videoRef,
    canvasRef: lightingCanvasRef,
    enabled: isReady && isPassportDetected && !capturedImage && !cameraError,
  });
  const { status: glareStatus, hasGlare } = usePassportGlareDetection({
    videoRef,
    canvasRef: glareCanvasRef,
    enabled: isReady && isPassportDetected && !capturedImage && !cameraError,
  });

  const isCaptureReady = isPassportDetected && isSharp && isWellLit && !hasGlare && !isProcessingCapture;

  const guideToneClass = isCaptureReady
    ? "border-emerald-400"
    : isPassportDetected
      ? "border-amber-400"
      : "border-white/60";

  const statusBannerClass = isCaptureReady
    ? "bg-emerald-500 text-white"
    : isPassportDetected
      ? "bg-amber-500 text-slate-950"
      : "bg-black/55 text-white/90";

  const guidanceMessage = isProcessingCapture
    ? `Straightening and saving the passport ${pageSide} page`
    : isCaptureReady && autoCaptureProgress.isComplete
      ? "Stability confirmed - capturing now"
    : isCaptureReady
      ? `Hold steady - ${autoCaptureProgress.secondsRemaining || 1}s until automatic capture`
    : !isPassportDetected
    ? `Position the passport ${pageSide === "front" ? "data" : "back"} page within the frame`
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

      try {
        if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
          setCameraError(
            "This custom passport scanner needs a secure camera session. Open the upload link over HTTPS to use the live detection frame, glare, blur, and lighting checks.",
          );
          return;
        }

        stopCamera();

        const mediaStream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: facingMode },
            width: { ideal: 1920 },
            height: { ideal: 1080 },
          },
          audio: false,
        });

        if (disposed) {
          mediaStream.getTracks().forEach((track) => track.stop());
          return;
        }

        streamRef.current = mediaStream;
        if (videoRef.current) {
          videoRef.current.srcObject = mediaStream;
          await videoRef.current.play().catch(() => undefined);
        }
      } catch (error) {
        if (disposed) return;
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
  }, [allowFileFallback, cameraRestartGeneration, facingMode, stopCamera]);

  const clearAutoCaptureTimers = useCallback(() => {
    autoCaptureStableSinceRef.current = null;
    if (autoCaptureTimeoutRef.current !== null) {
      window.clearTimeout(autoCaptureTimeoutRef.current);
      autoCaptureTimeoutRef.current = null;
    }

    if (autoCaptureIntervalRef.current !== null) {
      window.clearInterval(autoCaptureIntervalRef.current);
      autoCaptureIntervalRef.current = null;
    }
  }, []);

  const toggleCamera = () => {
    clearAutoCaptureTimers();
    setAutoCaptureProgress(getEmptyPassportAutoCaptureProgress());
    setIsReady(false);
    setFacingMode((prev) => prev === "environment" ? "user" : "environment");
  };

  const takePhoto = useCallback(async () => {
    if (!videoRef.current || !canvasRef.current || !isReady) return;

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
      clearAutoCaptureTimers();

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
        );
        if (!mountedRef.current) return;
        setCapturedFile(normalized.file);
        setCapturedImage(normalized.previewDataUrl);
        stopCamera();
      } catch {
        stopCamera();
        if (mountedRef.current) {
          setCameraError(
            `The passport ${pageSide} page could not be prepared. Try the camera again or go back and choose another capture method.`,
          );
        }
      } finally {
        if (mountedRef.current) setIsProcessingCapture(false);
      }
    }
  }, [clearAutoCaptureTimers, isReady, pageSide, stopCamera]);

  const restartCamera = () => {
    clearAutoCaptureTimers();
    stopCamera();
    setCameraError(null);
    setCapturedImage(null);
    setCapturedFile(null);
    setIsReady(false);
    setAutoCaptureProgress(getEmptyPassportAutoCaptureProgress());
    setCameraRestartGeneration((generation) => generation + 1);
  };

  const retake = () => {
    clearAutoCaptureTimers();
    setCapturedImage(null);
    setCapturedFile(null);
    setAutoCaptureProgress(getEmptyPassportAutoCaptureProgress());
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
    clearAutoCaptureTimers();
    stopCamera();
    onCancel();
  };

  useEffect(() => {
    if (!isCaptureReady || capturedImage || cameraError) {
      clearAutoCaptureTimers();
      autoCaptureTimeoutRef.current = window.setTimeout(() => {
        if (mountedRef.current) {
          setAutoCaptureProgress(getEmptyPassportAutoCaptureProgress());
        }
      }, 0);
      return () => {
        clearAutoCaptureTimers();
      };
    }

    clearAutoCaptureTimers();
    const stableSince = window.performance.now();
    autoCaptureStableSinceRef.current = stableSince;
    const updateProgress = () => {
      if (autoCaptureStableSinceRef.current !== stableSince || !mountedRef.current) return;
      const nextProgress = getPassportAutoCaptureProgress(
        stableSince,
        window.performance.now(),
      );
      setAutoCaptureProgress(nextProgress);
      if (!nextProgress.isComplete) return;
      clearAutoCaptureTimers();
      void takePhoto();
    };
    autoCaptureTimeoutRef.current = window.setTimeout(updateProgress, 0);
    autoCaptureIntervalRef.current = window.setInterval(
      updateProgress,
      PASSPORT_AUTO_CAPTURE_TICK_MS,
    );

    return () => {
      clearAutoCaptureTimers();
    };
  }, [cameraError, capturedImage, clearAutoCaptureTimers, isCaptureReady, takePhoto]);

  useEffect(() => {
    return () => {
      clearAutoCaptureTimers();
    };
  }, [clearAutoCaptureTimers]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-slate-950 text-white">
      <div className="flex h-16 items-center justify-between px-4 pt-[max(0.25rem,env(safe-area-inset-top))]">
        <button
          type="button"
          onClick={close}
          aria-label="Close camera"
          className="rounded-full p-2 text-white/80 transition-colors hover:bg-white/10 hover:text-white"
        >
          <X className="h-6 w-6" />
        </button>
        <h2 className="text-lg font-semibold tracking-tight">
          Passport {pageSide === "front" ? "Front" : "Back"} Scan
        </h2>
        <div className="w-10" aria-hidden="true" />
      </div>

      <div className="relative flex flex-1 flex-col items-center justify-center overflow-hidden bg-black">
        {(isLoading || isProcessingCapture) && !capturedImage && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-slate-950">
            <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
          </div>
        )}

        {cameraError ? (
          <div className="mx-6 max-w-md rounded-2xl border border-amber-400/30 bg-slate-900 p-6 text-center shadow-2xl">
            <AlertTriangle className="mx-auto mb-4 h-10 w-10 text-amber-400" />
            <h3 className="mb-2 text-lg font-semibold">Camera unavailable</h3>
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
              className={`h-full w-full object-cover ${capturedImage ? "opacity-0" : "opacity-100"} ${facingMode === "user" ? "scale-x-[-1]" : ""}`}
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
                  {isPassportDetected && !isProcessingCapture && (
                    <div
                      className="mt-2 h-1.5 overflow-hidden rounded-full bg-black/20"
                      role="progressbar"
                      aria-label="Passport stability before automatic capture"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={Math.round(autoCaptureProgress.progress * 100)}
                    >
                      <div
                        className="h-full rounded-full bg-white transition-[width] duration-150 ease-out"
                        style={{ width: `${Math.round(autoCaptureProgress.progress * 100)}%` }}
                      />
                    </div>
                  )}
                </div>

                <div className="absolute bottom-28 left-1/2 flex max-w-[94%] -translate-x-1/2 flex-wrap items-center justify-center gap-2 sm:bottom-24">
                  <QualityChip label="Passport" status={isPassportDetected ? "ready" : "pending"} />
                  <QualityChip
                    label="Focus"
                    status={!isPassportDetected || blurStatus === "checking" ? "pending" : isSharp ? "ready" : "warning"}
                  />
                  <QualityChip
                    label="Lighting"
                    status={!isPassportDetected || lightingStatus === "checking" ? "pending" : lightingStatus === "good" ? "ready" : "warning"}
                  />
                  <QualityChip
                    label="Glare"
                    status={!isPassportDetected || glareStatus === "checking" ? "pending" : hasGlare ? "warning" : "ready"}
                  />
                  <QualityChip
                    label={isCaptureReady
                      ? `Auto ${autoCaptureProgress.secondsRemaining || "now"}`
                      : "Auto"}
                    status={!isPassportDetected ? "pending" : isCaptureReady ? "ready" : "pending"}
                  />
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
              <button
                type="button"
                onClick={toggleCamera}
                aria-label="Switch camera"
                className="rounded-full bg-white/10 p-3 transition-colors hover:bg-white/20"
              >
                <RefreshCcw className="h-6 w-6 text-white" />
              </button>
              <button
                type="button"
                onClick={() => void takePhoto()}
                disabled={!isReady || isProcessingCapture}
                aria-label="Take photo"
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

interface QualityChipProps {
  label: string;
  status: "ready" | "warning" | "pending";
}

function QualityChip({ label, status }: QualityChipProps) {
  const toneClass = status === "ready"
    ? "border-emerald-400/40 bg-emerald-500/15 text-emerald-100"
    : status === "warning"
      ? "border-amber-300/40 bg-amber-400/15 text-amber-50"
      : "border-white/10 bg-black/35 text-white/70";

  return (
    <div className={`rounded-full border px-3 py-1.5 text-xs font-medium shadow-sm backdrop-blur ${toneClass}`}>
      {label}
    </div>
  );
}

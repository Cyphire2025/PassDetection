"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Image from "next/image";
import { AlertTriangle, RefreshCcw, X, Check, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { usePassportFrameDetection } from "../hooks/use-passport-frame-detection";
import { usePassportBlurDetection } from "../hooks/use-passport-blur-detection";
import { usePassportLightingDetection } from "../hooks/use-passport-lighting-detection";
import { usePassportGlareDetection } from "../hooks/use-passport-glare-detection";
import { getPassportAnalysisBounds } from "../services/passport-analysis-region";
import { normalizePassportCanvasCapture } from "../services/passport-perspective-correction";

interface SmartCameraProps {
  onCapture: (file: File) => void;
  onCancel: () => void;
}

export function SmartCamera({ onCapture, onCancel }: SmartCameraProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const analysisCanvasRef = useRef<HTMLCanvasElement>(null);
  const blurCanvasRef = useRef<HTMLCanvasElement>(null);
  const lightingCanvasRef = useRef<HTMLCanvasElement>(null);
  const glareCanvasRef = useRef<HTMLCanvasElement>(null);
  const [facingMode, setFacingMode] = useState<"environment" | "user">("environment");
  const [capturedImage, setCapturedImage] = useState<string | null>(null);
  const [capturedFile, setCapturedFile] = useState<File | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isReady, setIsReady] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [isProcessingCapture, setIsProcessingCapture] = useState(false);
  const [wasPerspectiveCorrected, setWasPerspectiveCorrected] = useState(false);
  const [autoCaptureCountdown, setAutoCaptureCountdown] = useState<number | null>(null);
  const autoCaptureTimeoutRef = useRef<number | null>(null);
  const autoCaptureIntervalRef = useRef<number | null>(null);

  const { isDetected: isPassportDetected } = usePassportFrameDetection({
    videoRef,
    canvasRef: analysisCanvasRef,
    enabled: isReady && !capturedImage && !cameraError,
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
    ? "Aligning passport edges"
    : autoCaptureCountdown !== null && autoCaptureCountdown > 0
      ? `Hold steady - capturing in ${autoCaptureCountdown}`
    : !isPassportDetected
    ? "Position the data page within the frame"
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

  useEffect(() => {
    let currentStream: MediaStream | null = null;

    async function startCamera() {
      setIsLoading(true);
      setIsReady(false);
      setCameraError(null);

      try {
        if (currentStream) {
          currentStream.getTracks().forEach((track) => track.stop());
        }

        const mediaStream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode,
            width: { ideal: 1920 },
            height: { ideal: 1080 },
          },
          audio: false,
        });

        currentStream = mediaStream;
        if (videoRef.current) {
          videoRef.current.srcObject = mediaStream;
        }
      } catch (error) {
        console.error("Failed to access camera", error);
        setCameraError(
          error instanceof DOMException && error.name === "NotAllowedError"
            ? "Camera access was blocked. Allow camera permission in your browser and try again."
            : "The camera could not be started. You can go back and upload a photo instead.",
        );
      } finally {
        setIsLoading(false);
      }
    }

    startCamera();

    return () => {
      if (currentStream) {
        currentStream.getTracks().forEach((track) => track.stop());
      }
    };
  }, [facingMode]);

  const toggleCamera = () => {
    setFacingMode((prev) => prev === "environment" ? "user" : "environment");
  };

  const clearAutoCaptureTimers = useCallback(() => {
    if (autoCaptureTimeoutRef.current !== null) {
      window.clearTimeout(autoCaptureTimeoutRef.current);
      autoCaptureTimeoutRef.current = null;
    }

    if (autoCaptureIntervalRef.current !== null) {
      window.clearInterval(autoCaptureIntervalRef.current);
      autoCaptureIntervalRef.current = null;
    }
  }, []);

  const takePhoto = useCallback(async () => {
    if (!videoRef.current || !canvasRef.current || !isReady) return;

    const video = videoRef.current;
    const canvas = canvasRef.current;
    const bounds = getPassportAnalysisBounds(video.videoWidth, video.videoHeight);
    const cropWidth = Math.max(1, bounds.right - bounds.left);
    const cropHeight = Math.max(1, bounds.bottom - bounds.top);

    canvas.width = cropWidth;
    canvas.height = cropHeight;

    const context = canvas.getContext("2d");
    if (context) {
      setIsProcessingCapture(true);
      clearAutoCaptureTimers();
      setAutoCaptureCountdown(null);

      try {
        context.drawImage(
          video,
          bounds.left,
          bounds.top,
          cropWidth,
          cropHeight,
          0,
          0,
          cropWidth,
          cropHeight,
        );

        const normalized = await normalizePassportCanvasCapture(canvas);
        setCapturedFile(normalized.file);
        setCapturedImage(normalized.previewDataUrl);
        setWasPerspectiveCorrected(normalized.corrected);
      } finally {
        setIsProcessingCapture(false);
      }
    }
  }, [clearAutoCaptureTimers, isReady]);

  const retake = () => {
    clearAutoCaptureTimers();
    setCapturedImage(null);
    setCapturedFile(null);
    setWasPerspectiveCorrected(false);
    setAutoCaptureCountdown(null);
  };

  const confirm = () => {
    if (!capturedFile) return;
    onCapture(capturedFile);
  };

  useEffect(() => {
    if (!isCaptureReady || capturedImage || cameraError) {
      clearAutoCaptureTimers();
      return;
    }

    autoCaptureTimeoutRef.current = window.setTimeout(() => {
      setAutoCaptureCountdown(3);
    }, 0);

    autoCaptureIntervalRef.current = window.setInterval(() => {
      setAutoCaptureCountdown((current) => {
        if (current === null || current <= 1) {
          return 1;
        }
        return current - 1;
      });
    }, 400);

    const captureTimeout = window.setTimeout(() => {
      void takePhoto();
    }, 1200);

    return () => {
      window.clearTimeout(captureTimeout);
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
          onClick={onCancel}
          aria-label="Close camera"
          className="rounded-full p-2 text-white/80 transition-colors hover:bg-white/10 hover:text-white"
        >
          <X className="h-6 w-6" />
        </button>
        <h2 className="text-lg font-semibold tracking-tight">Passport Scan</h2>
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
            <Button onClick={onCancel} className="w-full">
              Upload a file instead
            </Button>
          </div>
        ) : capturedImage ? (
          <Image
            src={capturedImage}
            alt="Captured passport"
            fill
            unoptimized
            className="object-contain"
          />
        ) : (
          <>
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              onLoadedData={() => setIsReady(true)}
              className={`h-full w-full object-cover ${facingMode === "user" ? "scale-x-[-1]" : ""}`}
            />

            <div className="pointer-events-none absolute inset-0">
              <div className="absolute left-1/2 top-1/2 h-auto w-[min(88vw,34rem)] -translate-x-1/2 -translate-y-1/2 aspect-[1.42/1] max-h-[56vh]">
                <div className={`absolute inset-0 rounded-[22px] border-2 transition-colors shadow-[0_0_0_9999px_rgba(2,6,23,0.44)] ${guideToneClass}`}>
                  <div className="absolute -left-1 -top-1 h-8 w-8 rounded-tl-lg border-l-4 border-t-4 border-blue-500"></div>
                  <div className="absolute -right-1 -top-1 h-8 w-8 rounded-tr-lg border-r-4 border-t-4 border-blue-500"></div>
                  <div className="absolute -bottom-1 -left-1 h-8 w-8 rounded-bl-lg border-b-4 border-l-4 border-blue-500"></div>
                  <div className="absolute -bottom-1 -right-1 h-8 w-8 rounded-br-lg border-b-4 border-r-4 border-blue-500"></div>
                </div>
              </div>

              <div
                className={`absolute left-1/2 top-5 w-max max-w-[92%] -translate-x-1/2 rounded-full px-4 py-2 text-center text-sm font-medium shadow-lg backdrop-blur ${statusBannerClass}`}
              >
                {guidanceMessage}
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
                  label="Auto"
                  status={!isPassportDetected ? "pending" : isCaptureReady ? "ready" : "pending"}
                />
              </div>
            </div>
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
              {wasPerspectiveCorrected && (
                <div className="rounded-full border border-emerald-400/30 bg-emerald-500/10 px-3 py-1 text-center text-xs font-medium text-emerald-100 sm:hidden">
                  Edges aligned automatically
                </div>
              )}
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

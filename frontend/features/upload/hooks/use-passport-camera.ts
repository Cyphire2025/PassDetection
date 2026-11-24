"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { SmartCameraProps } from "../components/passport-camera.types";
import { useCameraCaptureLifecycle } from "./use-camera-capture-lifecycle";
import { usePassportCameraSession } from "./use-passport-camera-session";
import { usePassportFrameDetection } from "./use-passport-frame-detection";
import { useStableTelemetryReason } from "./use-stable-telemetry-reason";
import { normalizePassportCanvasCapture } from "../services/passport-perspective-correction";
import { captureBestCameraSource, remapVideoCropToSource } from "../services/camera-capture";
import { validatePassportFinalFile, type PassportFinalQualityResult } from "../services/passport-final-quality";
import { passportScannerRejectionReason } from "../services/public-flow-telemetry";
import { getVisibleGuideCrop, addCaptureMargin } from "../services/passport-camera-crop";
import { passportFrameGuidance } from "../services/passport-camera-guidance";

export function usePassportCamera({
  onCapture, onCancel, pageSide, allowFileFallback = true,
  onTelemetryReason = () => undefined,
}: SmartCameraProps) {
  const captureLifecycle = useCameraCaptureLifecycle();
  const guideRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const analysisCanvasRef = useRef<HTMLCanvasElement>(null);
  const captureStartedRef = useRef(false);
  const [capturedImage, setCapturedImage] = useState<string | null>(null);
  const [capturedFile, setCapturedFile] = useState<File | null>(null);
  const [finalQuality, setFinalQuality] =
    useState<PassportFinalQualityResult | null>(null);
  const [borderlineConfirmed, setBorderlineConfirmed] = useState(false);
  const [isProcessingCapture, setIsProcessingCapture] = useState(false);

  const onSuspend = useCallback(() => {
    captureLifecycle.invalidate();
    captureStartedRef.current = false;
    setIsProcessingCapture(false);
  }, [captureLifecycle]);
  const session = usePassportCameraSession({ allowFileFallback, capturedImage, onSuspend });
  const {
    videoRef, streamRef, cameraRestartGeneration, isReady,
    cameraError, setCameraError, failureReason, setFailureReason, stopCamera, restartSession,
  } = session;

  const {
    isDetected: isPassportDetected,
    status: passportFrameStatus,
    hasDocumentCandidate,
    lightingStatus,
  } = usePassportFrameDetection({
    videoRef,
    canvasRef: analysisCanvasRef,
    guideRef,
    enabled: isReady && !capturedImage && !cameraError,
    resetKey: cameraRestartGeneration,
  });

  const isCaptureReady = isPassportDetected
    && !isProcessingCapture;

  const telemetryReason = passportScannerRejectionReason({
    failureReason,
    frameStatus: passportFrameStatus,
    passportDetected: isPassportDetected,
    glareStatus: "clear",
    lightingStatus,
    blurStatus: "sharp",
  });
  useStableTelemetryReason(telemetryReason, onTelemetryReason);

  const guideToneClass = isCaptureReady
    ? "border-emerald-500"
    : hasDocumentCandidate
      ? "border-amber-400"
      : "border-blue-500";

  const guideCornerToneClass = isCaptureReady
    ? "border-emerald-500"
    : hasDocumentCandidate
      ? "border-amber-400"
      : "border-blue-500";

  const statusBannerClass = isCaptureReady
    ? "border-emerald-300 bg-emerald-50/95 text-emerald-900"
    : hasDocumentCandidate
      ? "border-amber-300 bg-amber-50/95 text-amber-950"
      : "border-blue-200 bg-white/95 text-slate-800";

  const guidanceMessage = isProcessingCapture
    ? `Preparing and checking the passport ${pageSide} page`
    : isCaptureReady
      ? "Ready to capture"
    : lightingStatus === "too_dark"
      ? "Move into brighter, even lighting"
    : lightingStatus === "too_bright"
      ? "Reduce harsh light on the passport"
    : !isPassportDetected
    ? passportFrameGuidance(passportFrameStatus, pageSide)
    : "Hold the passport steady inside the guide";

  useEffect(() => () => {
    if (capturedImage?.startsWith("blob:")) {
      URL.revokeObjectURL(capturedImage);
    }
  }, [capturedImage]);

  const takePhoto = useCallback(async () => {
    if (
      !videoRef.current
      || !canvasRef.current
      || !isReady
      || !isCaptureReady
      || captureStartedRef.current
    ) return;

    const video = videoRef.current;
    const canvas = canvasRef.current;
    // Keep minimal context around every side of the guide so the shared
    // normalizer has enough boundary pixels for perspective rectification.
    const crop = addCaptureMargin(getVisibleGuideCrop(video, guideRef.current), video.videoWidth, video.videoHeight);
    captureStartedRef.current = true;
    const isCurrentCapture = captureLifecycle.begin();
    setIsProcessingCapture(true);
    setBorderlineConfirmed(false);
    setFinalQuality(null);

    try {
      const source = await captureBestCameraSource(
        video,
        streamRef.current,
      );
      try {
        if (!isCurrentCapture()) return;
        const sourceCrop = remapVideoCropToSource(
          crop,
          video.videoWidth,
          video.videoHeight,
          source.width,
          source.height,
        );
        const maximumCaptureDimension = 2400;
        const captureScale = Math.min(
          1,
          maximumCaptureDimension
            / Math.max(sourceCrop.width, sourceCrop.height),
        );
        const cropWidth = Math.max(
          1,
          Math.round(sourceCrop.width * captureScale),
        );
        const cropHeight = Math.max(
          1,
          Math.round(sourceCrop.height * captureScale),
        );
        canvas.width = cropWidth;
        canvas.height = cropHeight;
        const context = canvas.getContext("2d");
        if (!context) {
          throw new Error("This browser cannot prepare a camera image.");
        }
        context.drawImage(
          source.image,
          sourceCrop.left,
          sourceCrop.top,
          sourceCrop.width,
          sourceCrop.height,
          0,
          0,
          cropWidth,
          cropHeight,
        );
      } finally {
        source.close();
      }

      const normalized = await normalizePassportCanvasCapture(
        canvas,
        `passport-${pageSide}-capture.jpg`,
        pageSide,
      );
      if (!isCurrentCapture()) return;
      const quality = await validatePassportFinalFile(
        normalized.file,
        pageSide,
      );
      if (!isCurrentCapture()) return;
      setCapturedFile(normalized.file);
      setCapturedImage(URL.createObjectURL(normalized.file));
      setFinalQuality(quality);
      setFailureReason(null);
      stopCamera();
    } catch {
      if (!isCurrentCapture()) return;
      stopCamera();
      setFailureReason("crop_validation_failed");
      setCameraError(
        `The passport ${pageSide} page could not be prepared. Try the camera again or go back and choose another capture method.`,
      );
    } finally {
      if (isCurrentCapture()) {
        captureStartedRef.current = false;
        setIsProcessingCapture(false);
      }
    }
  }, [
    captureLifecycle,
    isCaptureReady,
    isReady,
    pageSide,
    setCameraError,
    setFailureReason,
    stopCamera,
    streamRef,
    videoRef,
  ]);

  const restartCamera = () => {
    captureLifecycle.invalidate();
    captureStartedRef.current = false;
    setIsProcessingCapture(false);
    stopCamera();
    setCameraError(null);
    setFailureReason(null);
    setCapturedImage(null);
    setCapturedFile(null);
    setFinalQuality(null);
    setBorderlineConfirmed(false);
    restartSession();
  };

  const retake = () => {
    captureLifecycle.invalidate();
    setCapturedImage(null);
    setCapturedFile(null);
    setFinalQuality(null);
    setBorderlineConfirmed(false);
    setIsProcessingCapture(false);

    restartSession();
  };

  const confirm = () => {
    if (!capturedFile || !finalQuality) return;
    if (finalQuality.outcome === "hard_failure") return;
    if (
      finalQuality.outcome === "borderline"
      && !borderlineConfirmed
    ) return;
    stopCamera();
    onCapture(capturedFile);
  };

  const close = () => {
    captureLifecycle.invalidate();
    stopCamera();
    onCancel();
  };
  return {
    ...session, pageSide, guideRef, canvasRef, analysisCanvasRef,
    capturedImage, finalQuality, borderlineConfirmed, setBorderlineConfirmed,
    isProcessingCapture, isCaptureReady, guideToneClass, guideCornerToneClass,
    statusBannerClass, guidanceMessage, takePhoto, restartCamera, retake, confirm, close,
  };
}

export type PassportCameraController = ReturnType<typeof usePassportCamera>;

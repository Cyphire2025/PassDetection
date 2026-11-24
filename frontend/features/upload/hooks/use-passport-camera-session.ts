"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export function usePassportCameraSession({ allowFileFallback, capturedImage, onSuspend }: {
  allowFileFallback: boolean;
  capturedImage: string | null;
  onSuspend: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const visibilityPausedRef = useRef(false);
  const [cameraRestartGeneration, setCameraRestartGeneration] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [isReady, setIsReady] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [failureReason, setFailureReason] = useState<"camera_unavailable" | "crop_validation_failed" | null>(null);

  const stopCamera = useCallback(() => {
    if (videoRef.current) {
      videoRef.current.pause();
      videoRef.current.srcObject = null;
    }
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  useEffect(() => {
    let disposed = false;

    async function startCamera() {
      setIsLoading(true);
      setIsReady(false);
      setCameraError(null);
      setFailureReason(null);

      try {
        if (isPageHidden()) {
          visibilityPausedRef.current = true;
          return;
        }
        if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
          setFailureReason("camera_unavailable");
          setCameraError(
            "This custom passport scanner needs a secure camera session. Open the upload link over HTTPS to use the live positioning and lighting checks.",
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
        onSuspend();
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
  }, [onSuspend, capturedImage, stopCamera]);

  const restartSession = () => {
    setIsReady(false);
    setCameraRestartGeneration(generation => generation + 1);
  };

  return {
    videoRef, streamRef, cameraRestartGeneration, isLoading, isReady,
    setIsReady, cameraError, setCameraError, failureReason, setFailureReason,
    stopCamera, restartSession,
  };
}

function isPageHidden() {
  return document.visibilityState === "hidden";
}

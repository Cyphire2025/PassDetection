"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { BrowserCodeReader, BrowserQRCodeReader, type IScannerControls } from "@zxing/browser";

export interface QrScanResult {
  id: string;
  text: string;
  scannedAt: string;
}

export type ScannerStatus = "idle" | "starting" | "scanning" | "error";

/** Passenger QR codes are shared by attendance and hotel check-in. */
export const PASSENGER_QR_PATTERN = /^pdatt:[A-Za-z0-9_-]{43}$/;
const SAME_PAYLOAD_SUPPRESSION_MS = 2500;
const DECODE_INTERVAL_MS = 110;

export function useContinuousQrScanner({
  payloadPattern = PASSENGER_QR_PATTERN,
  trackStats = false,
  canAutoResume,
}: {
  payloadPattern?: RegExp;
  trackStats?: boolean;
  canAutoResume?: () => boolean;
} = {}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const controlsRef = useRef<IScannerControls | null>(null);
  const scannerGenerationRef = useRef(0);
  const selectedDeviceIdRef = useRef<string | undefined>(undefined);
  const resumeWhenVisibleRef = useRef(false);
  const canAutoResumeRef = useRef(canAutoResume);
  const duplicateCountRef = useRef(0);
  const lastScanRef = useRef<{ text: string; at: number } | null>(null);
  const [status, setStatus] = useState<ScannerStatus>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | undefined>();
  const [latestScan, setLatestScan] = useState<QrScanResult | null>(null);
  const [scanHistory, setScanHistory] = useState<QrScanResult[]>([]);
  const [duplicateCount, setDuplicateCount] = useState(0);
  const [isTorchOn, setIsTorchOn] = useState(false);
  const [supportsTorch, setSupportsTorch] = useState(false);

  useEffect(() => {
    canAutoResumeRef.current = canAutoResume;
  }, [canAutoResume]);

  const refreshDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    const availableDevices = await BrowserCodeReader.listVideoInputDevices();
    setDevices(availableDevices);
    setSelectedDeviceId((current) => {
      const next = current ?? preferBackCamera(availableDevices)?.deviceId;
      selectedDeviceIdRef.current = next;
      return next;
    });
  }, []);

  const stopScanner = useCallback(() => {
    scannerGenerationRef.current += 1;
    controlsRef.current?.stop();
    controlsRef.current = null;
    setStatus("idle");
    setIsTorchOn(false);
    setSupportsTorch(false);
    BrowserCodeReader.releaseAllStreams();
  }, []);

  const handleScanResult = useCallback((result?: { getText(): string }) => {
    if (!result) {
      return;
    }

    const text = result.getText().trim();
    if (!payloadPattern.test(text)) return;

    const now = Date.now();
    const previous = lastScanRef.current;
    const isDuplicate = previous?.text === text && now - previous.at < SAME_PAYLOAD_SUPPRESSION_MS;

    if (isDuplicate) {
      duplicateCountRef.current += 1;
      if (trackStats) setDuplicateCount(duplicateCountRef.current);
      return;
    }

    lastScanRef.current = { text, at: now };
    const scan: QrScanResult = {
      id: `${now}-${Math.random().toString(36).slice(2)}`,
      text,
      scannedAt: new Date(now).toISOString(),
    };
    setLatestScan(scan);
    if (trackStats) setScanHistory((history) => [scan, ...history].slice(0, 8));
    navigator.vibrate?.(60);
  }, [payloadPattern, trackStats]);

  const startScanner = useCallback(async () => {
    if (!videoRef.current) return;

    const scannerGeneration = scannerGenerationRef.current + 1;
    scannerGenerationRef.current = scannerGeneration;
    controlsRef.current?.stop();
    controlsRef.current = null;
    BrowserCodeReader.releaseAllStreams();
    setStatus("starting");
    setErrorMessage(null);
    setSupportsTorch(false);
    setIsTorchOn(false);

    try {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        throw new Error("Open this page over HTTPS or localhost to allow browser camera access.");
      }

      const reader = new BrowserQRCodeReader(undefined, {
        delayBetweenScanAttempts: DECODE_INTERVAL_MS,
        delayBetweenScanSuccess: DECODE_INTERVAL_MS,
        tryPlayVideoTimeout: 5000,
      });

      const selectedDevice = selectedDeviceIdRef.current;
      const controls = selectedDevice
        ? await reader.decodeFromVideoDevice(selectedDevice, videoRef.current, handleScanResult)
        : await reader.decodeFromConstraints(
            {
              video: {
                facingMode: { ideal: "environment" },
                width: { ideal: 960, max: 1280 },
                height: { ideal: 540, max: 720 },
                frameRate: { ideal: 24, max: 30 },
              },
              audio: false,
            },
            videoRef.current,
            handleScanResult,
          );

      if (scannerGenerationRef.current !== scannerGeneration) {
        controls.stop();
        return;
      }
      controlsRef.current = controls;
      setSupportsTorch(Boolean(controls.switchTorch));
      setStatus("scanning");
      await refreshDevices();
    } catch (error) {
      if (scannerGenerationRef.current !== scannerGeneration) return;
      console.error("QR scanner failed to start", error);
      setStatus("error");
      setErrorMessage(formatCameraError(error));
      BrowserCodeReader.releaseAllStreams();
    }
  }, [handleScanResult, refreshDevices]);

  const selectDevice = useCallback((deviceId: string | undefined) => {
    selectedDeviceIdRef.current = deviceId;
    setSelectedDeviceId(deviceId);
  }, []);

  const toggleTorch = useCallback(async () => {
    if (!controlsRef.current?.switchTorch) return;
    const nextValue = !isTorchOn;
    await controlsRef.current.switchTorch(nextValue);
    setIsTorchOn(nextValue);
  }, [isTorchOn]);

  const resetProofStats = useCallback(() => {
    setLatestScan(null);
    setScanHistory([]);
    setDuplicateCount(0);
    duplicateCountRef.current = 0;
    lastScanRef.current = null;
  }, []);

  useEffect(() => {
    const resumeScannerIfAllowed = () => {
      if (!resumeWhenVisibleRef.current) return;
      resumeWhenVisibleRef.current = false;
      if (canAutoResumeRef.current?.() ?? true) {
        void startScanner();
      }
    };
    const handleVisibility = () => {
      if (document.visibilityState === "hidden") {
        if (controlsRef.current !== null) {
          resumeWhenVisibleRef.current = true;
          stopScanner();
        }
        return;
      }
      resumeScannerIfAllowed();
    };
    const handlePageHide = () => {
      if (controlsRef.current !== null) {
        resumeWhenVisibleRef.current = true;
        stopScanner();
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    window.addEventListener("pagehide", handlePageHide);
    window.addEventListener("pageshow", resumeScannerIfAllowed);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibility);
      window.removeEventListener("pagehide", handlePageHide);
      window.removeEventListener("pageshow", resumeScannerIfAllowed);
      stopScanner();
    };
  }, [startScanner, stopScanner]);

  return {
    videoRef,
    status,
    errorMessage,
    devices,
    selectedDeviceId,
    latestScan,
    scanHistory,
    duplicateCount,
    supportsTorch,
    isTorchOn,
    setSelectedDeviceId: selectDevice,
    startScanner,
    stopScanner,
    toggleTorch,
    resetProofStats,
  };
}

function preferBackCamera(devices: MediaDeviceInfo[]) {
  return devices.find((device) => /back|rear|environment/i.test(device.label)) ?? devices[0];
}

function formatCameraError(error: unknown) {
  if (error instanceof DOMException && error.name === "NotAllowedError") {
    return "Camera permission was blocked. Allow camera access in the browser and start scanning again.";
  }

  if (error instanceof DOMException && error.name === "NotFoundError") {
    return "No camera was found on this device.";
  }

  if (error instanceof Error) {
    return error.message;
  }

  return "The QR scanner could not start on this browser.";
}

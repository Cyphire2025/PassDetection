"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { BrowserCodeReader, BrowserQRCodeReader, type IScannerControls } from "@zxing/browser";

export interface QrScanResult {
  id: string;
  text: string;
  scannedAt: string;
}

export type ScannerStatus = "idle" | "starting" | "scanning" | "error";

const ATTENDANCE_QR_PATTERN = /^pdatt:[0-9a-fA-F-]{36}$/;
const SAME_PAYLOAD_SUPPRESSION_MS = 1200;

export function useContinuousQrScanner() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const controlsRef = useRef<IScannerControls | null>(null);
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

  const refreshDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    const availableDevices = await BrowserCodeReader.listVideoInputDevices();
    setDevices(availableDevices);
    setSelectedDeviceId((current) => current ?? preferBackCamera(availableDevices)?.deviceId);
  }, []);

  const stopScanner = useCallback(() => {
    controlsRef.current?.stop();
    controlsRef.current = null;
    setStatus("idle");
    setIsTorchOn(false);
    setSupportsTorch(false);
    BrowserCodeReader.releaseAllStreams();
  }, []);

  const handleScanResult = useCallback((result?: { getText(): string }, error?: { getKind?: () => string }) => {
    if (!result) {
      if (error && error.getKind?.() !== "NotFoundException") {
        console.debug("QR scanner decode attempt failed", error);
      }
      return;
    }

    const text = result.getText().trim();
    if (!ATTENDANCE_QR_PATTERN.test(text)) return;

    const now = Date.now();
    const previous = lastScanRef.current;
    const isDuplicate = previous?.text === text && now - previous.at < SAME_PAYLOAD_SUPPRESSION_MS;

    if (isDuplicate) {
      setDuplicateCount((count) => count + 1);
      return;
    }

    lastScanRef.current = { text, at: now };
    const scan: QrScanResult = {
      id: `${now}-${Math.random().toString(36).slice(2)}`,
      text,
      scannedAt: new Date(now).toISOString(),
    };
    setLatestScan(scan);
    setScanHistory((history) => [scan, ...history].slice(0, 8));
    navigator.vibrate?.(60);
  }, []);

  const startScanner = useCallback(async () => {
    if (!videoRef.current) return;

    setStatus("starting");
    setErrorMessage(null);
    setSupportsTorch(false);
    setIsTorchOn(false);

    try {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        throw new Error("Open this page over HTTPS or localhost to allow browser camera access.");
      }

      stopScanner();

      const reader = new BrowserQRCodeReader(undefined, {
        delayBetweenScanAttempts: 45,
        delayBetweenScanSuccess: 120,
        tryPlayVideoTimeout: 5000,
      });

      const controls = selectedDeviceId
        ? await reader.decodeFromVideoDevice(selectedDeviceId, videoRef.current, handleScanResult)
        : await reader.decodeFromConstraints(
            {
              video: {
                facingMode: { ideal: "environment" },
                width: { ideal: 1280 },
                height: { ideal: 720 },
                frameRate: { ideal: 30, max: 60 },
              },
              audio: false,
            },
            videoRef.current,
            handleScanResult,
          );

      controlsRef.current = controls;
      setSupportsTorch(Boolean(controls.switchTorch));
      setStatus("scanning");
      await refreshDevices();
    } catch (error) {
      console.error("QR scanner failed to start", error);
      setStatus("error");
      setErrorMessage(formatCameraError(error));
      BrowserCodeReader.releaseAllStreams();
    }
  }, [handleScanResult, refreshDevices, selectedDeviceId, stopScanner]);

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
    lastScanRef.current = null;
  }, []);

  useEffect(() => {
    return () => stopScanner();
  }, [stopScanner]);

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
    setSelectedDeviceId,
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

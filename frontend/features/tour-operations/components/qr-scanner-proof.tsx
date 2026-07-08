"use client";

import Link from "next/link";
import {
  AlertTriangle,
  Camera,
  CheckCircle2,
  Flashlight,
  FlashlightOff,
  History,
  Lock,
  RotateCcw,
  ScanLine,
  Square,
  Wifi,
} from "lucide-react";
import { Badge, Button } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { useContinuousQrScanner } from "../hooks/use-continuous-qr-scanner";

export function QrScannerProof() {
  const {
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
  } = useContinuousQrScanner();
  const isStarting = status === "starting";
  const isScanning = status === "scanning";
  const isSecureCameraContext =
    typeof window === "undefined" || (window.isSecureContext && Boolean(navigator.mediaDevices?.getUserMedia));

  return (
    <div className="min-h-[100svh] bg-slate-950 text-white md:rounded-xl md:border md:border-slate-800">
      <div className="mx-auto flex min-h-[100svh] w-full max-w-md flex-col">
        <header className="shrink-0 px-4 pb-3 pt-[max(1rem,env(safe-area-inset-top))]">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-xs font-medium uppercase text-slate-400">Tour Operations</p>
              <h1 className="text-xl font-bold text-white">Scanner Proof</h1>
            </div>
            <Badge variant={isScanning ? "success" : "outline"} dot={isScanning} className="bg-white/10 text-white">
              {statusLabel(status)}
            </Badge>
          </div>
        </header>

        <main className="flex flex-1 flex-col">
          <section className="relative min-h-0 flex-1 overflow-hidden bg-black">
          <video
            ref={videoRef}
            className="h-full w-full object-cover"
            muted
            playsInline
            autoPlay
          />

          <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-7">
            <div className="relative aspect-square w-full max-w-72 rounded-3xl border-4 border-white/80 shadow-[0_0_0_999px_rgba(2,6,23,0.48)]">
              <ScanLine className="absolute left-1/2 top-1/2 h-12 w-12 -translate-x-1/2 -translate-y-1/2 text-white/80" aria-hidden="true" />
            </div>
          </div>

          <div className="absolute left-3 right-3 top-3 flex items-center justify-between gap-2">
            <Badge variant={isScanning ? "success" : "default"}>{isScanning ? "Camera Live" : "Camera Idle"}</Badge>
            <Badge variant="outline" className="bg-white/90 text-slate-700">
              <Wifi className="h-3 w-3" aria-hidden="true" />
              PWA Ready
            </Badge>
          </div>

          {latestScan && (
            <div className="absolute bottom-3 left-3 right-3 rounded-xl border border-green-300 bg-green-50/95 p-4 text-green-900 shadow-lg">
              <div className="flex items-center gap-3">
                <CheckCircle2 className="h-6 w-6 shrink-0 text-green-600" aria-hidden="true" />
                <div className="min-w-0">
                  <p className="text-sm font-semibold">QR detected</p>
                  <p className="truncate text-xs">{latestScan.text}</p>
                </div>
              </div>
            </div>
          )}
          </section>

          <section className="shrink-0 space-y-3 bg-white px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-4 text-slate-950">
          {!isSecureCameraContext && (
            <div className="flex gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
              <Lock className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span>iPhone Safari only asks for camera permission on HTTPS. This LAN HTTP page can load, but the camera will not start.</span>
            </div>
          )}

          {errorMessage && (
            <div className="flex gap-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span>{errorMessage}</span>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <Metric label="Scans" value={scanHistory.length.toString()} />
            <Metric label="Duplicates" value={duplicateCount.toString()} />
          </div>

          {devices.length > 1 && (
            <label className="block text-sm font-medium text-slate-700">
              Camera
              <select
                value={selectedDeviceId ?? ""}
                onChange={(event) => setSelectedDeviceId(event.target.value || undefined)}
                disabled={isScanning || isStarting}
                className="mt-1 h-11 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
              >
                {devices.map((device, index) => (
                  <option key={device.deviceId} value={device.deviceId}>
                    {device.label || `Camera ${index + 1}`}
                  </option>
                ))}
              </select>
            </label>
          )}

          <div className="grid gap-3">
            {isScanning ? (
              <Button
                type="button"
                size="lg"
                variant="danger"
                onClick={stopScanner}
                leftIcon={<Square className="h-5 w-5" aria-hidden="true" />}
                className="h-16 text-lg"
              >
                Stop Scanning
              </Button>
            ) : (
              <Button
                type="button"
                size="lg"
                onClick={startScanner}
                isLoading={isStarting}
                leftIcon={<Camera className="h-5 w-5" aria-hidden="true" />}
                className="h-16 text-lg"
              >
                Start Scanning
              </Button>
            )}

            <div className="grid grid-cols-2 gap-3">
              <Button
                type="button"
                size="lg"
                variant="secondary"
                onClick={supportsTorch ? toggleTorch : resetProofStats}
                leftIcon={
                  supportsTorch
                    ? isTorchOn
                      ? <FlashlightOff className="h-5 w-5" aria-hidden="true" />
                      : <Flashlight className="h-5 w-5" aria-hidden="true" />
                    : <RotateCcw className="h-5 w-5" aria-hidden="true" />
                }
                className="h-12 text-sm"
              >
                {supportsTorch ? (isTorchOn ? "Torch Off" : "Torch On") : "Reset"}
              </Button>
              <Button type="button" variant="secondary" size="lg" onClick={resetProofStats} className="h-12 text-sm">
                Clear
              </Button>
            </div>
          </div>

          <Link href={ROUTES.coordinator as never} className="block text-center text-sm font-medium text-blue-700">
            Back to Coordinator
          </Link>
          </section>
        </main>

        <section className="border-t border-slate-800 bg-slate-900 p-4 text-white">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm font-semibold text-white">
              <History className="h-4 w-4 text-slate-500" aria-hidden="true" />
              Recent scans
            </div>
            <Button type="button" variant="ghost" size="sm" onClick={resetProofStats}>
              Clear
            </Button>
          </div>

          {scanHistory.length === 0 ? (
            <p className="rounded-lg border border-dashed border-slate-700 px-3 py-5 text-center text-sm text-slate-400">
              Start the scanner and present any QR code.
            </p>
          ) : (
            <div className="space-y-2">
              {scanHistory.map((scan) => (
                <div key={scan.id} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2">
                  <p className="truncate text-sm font-medium text-white">{scan.text}</p>
                  <p className="mt-0.5 text-xs text-slate-400">{formatTime(scan.scannedAt)}</p>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
      <p className="text-xs font-medium uppercase text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-bold text-slate-900">{value}</p>
    </div>
  );
}

function statusLabel(status: string) {
  if (status === "starting") return "Starting";
  if (status === "scanning") return "Scanning";
  if (status === "error") return "Needs Attention";
  return "Ready";
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

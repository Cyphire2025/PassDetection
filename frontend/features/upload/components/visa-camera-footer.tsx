"use client";

import { Button } from "@/components/ui/button";
import { type VisaCameraController } from "../hooks/use-visa-camera";
import { AlertTriangle, RefreshCcw, Check } from "lucide-react";

export function VisaCameraFooter({ camera }: { camera: VisaCameraController }) {
  const {
    isCameraReady, isDetectorReady, cameraError, fallbackAcknowledged, setFallbackAcknowledged,
    modelError, capturedFile, capturedPreview, finalValidation, borderlineConfirmed,
    setBorderlineConfirmed, isProcessing, retake, retryChecks, takePhoto, ready,
    fallbackCaptureAllowed, canUseCapturedPhoto, onCapture,
  } = camera;

  return <>{!cameraError && (
    <footer className="z-10 flex max-h-[52dvh] min-h-[8.75rem] flex-none items-center justify-center overflow-y-auto border-t border-slate-200 bg-white px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-3 shadow-[0_-8px_24px_rgba(15,23,42,0.08)]">
      {capturedPreview ? (
        <div className="w-full max-w-md space-y-3">
          {finalValidation && finalValidation.outcome !== "pass" && (
            <div
              role="alert"
              className={`flex gap-3 rounded-xl border p-3 text-left ${finalValidation.outcome === "hard_failure"
                ? "border-red-200 bg-red-50 text-red-950"
                : "border-amber-200 bg-amber-50 text-amber-950"
                }`}
            >
              <AlertTriangle
                className={`mt-0.5 h-5 w-5 shrink-0 ${finalValidation.outcome === "hard_failure"
                  ? "text-red-600"
                  : "text-amber-600"
                  }`}
                aria-hidden="true"
              />
              <p className="text-xs leading-5">
                {finalValidation.message}
              </p>
            </div>
          )}
          {finalValidation?.outcome === "borderline" && (
            <label
              htmlFor="visa-photo-borderline-confirmation"
              className="flex cursor-pointer items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-left"
            >
              <input
                id="visa-photo-borderline-confirmation"
                type="checkbox"
                checked={borderlineConfirmed}
                onChange={(event) =>
                  setBorderlineConfirmed(event.target.checked)}
                className="mt-1 h-4 w-4 shrink-0 rounded border-slate-300 text-blue-600 focus:ring-blue-600"
              />
              <span className="text-xs leading-5 text-slate-700">
                I confirm there is exactly one clear, fully visible face
                with open eyes, and the background is a plain white,
                off-white, or light-neutral wall.
              </span>
            </label>
          )}
          <div className="flex flex-col gap-3 sm:flex-row">
            <Button variant="outline" size="lg" onClick={retake} className="flex-1 border-slate-300 bg-white text-slate-700 hover:bg-slate-50">
              <RefreshCcw className="mr-2 h-4 w-4" /> Retake
            </Button>
            {canUseCapturedPhoto && (
              <Button
                size="lg"
                disabled={
                  finalValidation?.outcome === "borderline"
                  && !borderlineConfirmed
                }
                onClick={() => capturedFile && onCapture(capturedFile)}
                className="flex-1 bg-blue-600 hover:bg-blue-700"
              >
                <Check className="mr-2 h-4 w-4" /> Use Visa Photo
              </Button>
            )}
          </div>
        </div>
      ) : modelError ? (
        <div className="w-full max-w-lg space-y-3 py-1">
          <div
            role="alert"
            className="flex gap-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-left"
          >
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
            <div>
              <p className="text-sm font-semibold text-amber-950">Live checks unavailable</p>
              <p className="mt-1 text-xs leading-5 text-amber-900">
                {modelError} Retry the automatic checks, or carefully
                confirm every requirement before using the guided fallback.
              </p>
            </div>
          </div>

          <label
            htmlFor="visa-photo-fallback-confirmation"
            className="flex cursor-pointer items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-left"
          >
            <input
              id="visa-photo-fallback-confirmation"
              type="checkbox"
              checked={fallbackAcknowledged}
              onChange={(event) => setFallbackAcknowledged(event.target.checked)}
              className="mt-1 h-4 w-4 shrink-0 rounded border-slate-300 text-blue-600 focus:ring-blue-600"
            />
            <span className="text-xs leading-5 text-slate-700">
              I confirm there is exactly one person, their face is centred,
              fully visible and sharp, and the background is a plain white
              or off-white wall with good lighting.
            </span>
          </label>

          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <Button
              type="button"
              variant="outline"
              onClick={retryChecks}
              disabled={isProcessing}
              className="border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
            >
              <RefreshCcw className="mr-2 h-4 w-4" />
              Retry live checks
            </Button>
            <Button
              type="button"
              onClick={() => void takePhoto("fallback")}
              disabled={!fallbackCaptureAllowed || isProcessing}
              className="bg-blue-600 hover:bg-blue-700"
            >
              Capture with guided fallback
            </Button>
          </div>
        </div>
      ) : (
        <div className="grid w-full max-w-sm grid-cols-[1fr_auto_1fr] items-center gap-6">
          <div aria-hidden="true" />
          <div className="flex flex-col items-center gap-2 text-center">
            <button
              type="button"
              onClick={() => void takePhoto()}
              disabled={!isCameraReady || isProcessing || !isDetectorReady || !ready}
              aria-label="Capture Visa Photo manually"
              className="flex h-[4.5rem] w-[4.5rem] items-center justify-center rounded-full border-4 border-white bg-blue-600 shadow-lg ring-2 ring-blue-600 transition-transform active:scale-95 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:ring-slate-300 disabled:opacity-60"
            >
              <span className="h-14 w-14 rounded-full border border-white/70" />
            </button>
            <p className="w-40 text-xs leading-4 text-slate-500">
              {ready
                ? "Tap the shutter to capture"
                : "Capture unlocks when positioning checks pass"}
            </p>
          </div>
          <div aria-hidden="true" />
        </div>
      )}
    </footer>
  )}</>;
}

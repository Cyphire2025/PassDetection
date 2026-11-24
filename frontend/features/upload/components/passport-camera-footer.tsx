"use client";

import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { PassportCameraController } from "../hooks/use-passport-camera";

export function PassportCameraFooter({ camera }: { camera: PassportCameraController }) {
  const { cameraError, capturedImage, finalQuality, borderlineConfirmed,
    setBorderlineConfirmed, retake, confirm, takePhoto, isCaptureReady } = camera;
  return (
    <>
      {!cameraError && (
        <div className="z-20 flex min-h-32 items-center justify-center border-t border-slate-200 bg-white px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-4 shadow-[0_-6px_18px_rgba(15,23,42,0.08)] sm:min-h-36 sm:px-6 sm:pt-5">
          {capturedImage ? (
            <div className="mx-auto flex w-full max-w-md flex-col gap-3">
              {finalQuality && finalQuality.outcome !== "pass" && (
                <div
                  role={finalQuality.outcome === "hard_failure"
                    ? "alert"
                    : "status"}
                  className={`rounded-xl border px-4 py-3 text-sm leading-5 ${
                    finalQuality.outcome === "hard_failure"
                      ? "border-red-200 bg-red-50 text-red-900"
                      : "border-amber-200 bg-amber-50 text-amber-950"
                  }`}
                >
                  <p className="font-medium">
                    {finalQuality.message}
                  </p>
                  {finalQuality.outcome === "borderline" && (
                    <label className="mt-3 flex cursor-pointer items-start gap-2">
                      <input
                        type="checkbox"
                        checked={borderlineConfirmed}
                        onChange={(event) => {
                          setBorderlineConfirmed(event.target.checked);
                        }}
                        className="mt-0.5 h-4 w-4 rounded border-amber-400 text-blue-600 focus:ring-blue-600"
                      />
                      <span>
                        {finalQuality.confirmationPrompt}
                      </span>
                    </label>
                  )}
                </div>
              )}
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
                <Button
                  variant="outline"
                  size="lg"
                  onClick={retake}
                  className="flex-1"
                >
                  Retake
                </Button>
                {finalQuality
                  && finalQuality.outcome !== "hard_failure" && (
                  <Button
                    size="lg"
                    onClick={confirm}
                    disabled={
                      finalQuality.outcome === "borderline"
                      && !borderlineConfirmed
                    }
                    className="flex-1 bg-blue-600 font-medium text-white hover:bg-blue-500"
                  >
                    <Check className="mr-2 h-4 w-4" /> Use Photo
                  </Button>
                )}
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-2">
              <button
                type="button"
                onClick={() => void takePhoto()}
                disabled={!isCaptureReady}
                aria-label={
                  isCaptureReady
                    ? "Capture passport page"
                    : "Passport capture is unavailable until every check passes"
                }
                className={`flex h-20 w-20 items-center justify-center rounded-full border-4 bg-white shadow-lg ring-4 transition-all focus-visible:outline-none focus-visible:ring-offset-2 ${
                  isCaptureReady
                    ? "border-emerald-600 ring-emerald-100 hover:scale-95 focus-visible:ring-emerald-500"
                    : "cursor-not-allowed border-slate-300 ring-slate-100"
                }`}
              >
                <div
                  className={`h-14 w-14 rounded-full transition-colors ${
                    isCaptureReady ? "bg-emerald-600" : "bg-slate-200"
                  }`}
                ></div>
              </button>
              <p
                aria-hidden="true"
                className={`text-xs font-medium ${
                  isCaptureReady ? "text-emerald-700" : "text-slate-500"
                }`}
              >
                {isCaptureReady ? "Tap to capture" : "Align the passport to enable capture"}
              </p>
            </div>
          )}
        </div>
      )}
    </>
  );
}

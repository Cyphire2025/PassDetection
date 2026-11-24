"use client";

import { useRef } from "react";
import Image from "next/image";
import { AlertTriangle, X, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import type { PassportCameraController } from "../hooks/use-passport-camera";
import { PassportCameraFooter } from "./passport-camera-footer";

export function PassportCameraView({ camera }: { camera: PassportCameraController }) {
  const { pageSide, close, isLoading, isProcessingCapture, capturedImage, cameraError,
    failureReason, restartCamera, videoRef, setIsReady, guideRef, guideToneClass,
    guideCornerToneClass, statusBannerClass, guidanceMessage, canvasRef, analysisCanvasRef } = camera;
  const dialogRef = useRef<HTMLDivElement>(null);
  const handleKeyDown = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: true, onClose: close });

  return (
    <div
      ref={dialogRef}
      onKeyDown={handleKeyDown}
      role="dialog"
      aria-modal="true"
      aria-labelledby="passport-camera-title"
      className="fixed inset-0 z-50 flex min-h-[100dvh] flex-col overscroll-none bg-slate-50 text-slate-950"
    >
      <div className="z-20 flex min-h-16 items-center justify-between border-b border-slate-200 bg-white px-4 pb-3 pt-[max(0.75rem,env(safe-area-inset-top))] shadow-sm">
        <button
          type="button"
          onClick={close}
          aria-label="Close camera"
          className="rounded-full border border-slate-200 bg-white p-2 text-slate-600 shadow-sm transition-colors hover:bg-slate-100 hover:text-slate-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
        >
          <X className="h-6 w-6" />
        </button>
        <h2 id="passport-camera-title" className="text-lg font-semibold tracking-tight">
          Passport {pageSide === "front" ? "Front" : "Back"} Scan
        </h2>
        <div className="w-10" aria-hidden="true" />
      </div>

      <div className="relative flex flex-1 flex-col items-center justify-center overflow-hidden bg-slate-200">
        {(isLoading || isProcessingCapture) && !capturedImage && (
          <div
            role="status"
            aria-live="polite"
            className="absolute inset-0 z-10 flex items-center justify-center bg-slate-50"
          >
            <Loader2 className="h-8 w-8 animate-spin text-blue-600" aria-hidden="true" />
            <span className="sr-only">
              {isProcessingCapture ? "Preparing passport image" : "Starting camera"}
            </span>
          </div>
        )}

        {cameraError ? (
          <div
            role="alert"
            className="mx-6 max-w-md rounded-2xl border border-amber-200 bg-white p-6 text-center shadow-xl"
          >
            <AlertTriangle className="mx-auto mb-4 h-10 w-10 text-amber-500" aria-hidden="true" />
            <h3 className="mb-2 text-lg font-semibold">
              {failureReason === "crop_validation_failed"
                ? "Passport image needs another try"
                : "Camera unavailable"}
            </h3>
            <p className="mb-6 text-sm leading-6 text-slate-600">{cameraError}</p>
            <div className="flex flex-col gap-3">
              <Button onClick={restartCamera} className="w-full">
                Try Camera Again
              </Button>
              <Button variant="outline" onClick={close} className="w-full">
                Back
              </Button>
              <p className="text-xs text-slate-500">
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
                  <div className={`absolute inset-0 rounded-[22px] border-2 transition-colors duration-200 shadow-[0_0_0_9999px_rgba(15,23,42,0.34)] ${guideToneClass}`}>
                    <div className={`absolute -left-1 -top-1 h-8 w-8 rounded-tl-lg border-l-4 border-t-4 transition-colors duration-200 ${guideCornerToneClass}`}></div>
                    <div className={`absolute -right-1 -top-1 h-8 w-8 rounded-tr-lg border-r-4 border-t-4 transition-colors duration-200 ${guideCornerToneClass}`}></div>
                    <div className={`absolute -bottom-1 -left-1 h-8 w-8 rounded-bl-lg border-b-4 border-l-4 transition-colors duration-200 ${guideCornerToneClass}`}></div>
                    <div className={`absolute -bottom-1 -right-1 h-8 w-8 rounded-br-lg border-b-4 border-r-4 transition-colors duration-200 ${guideCornerToneClass}`}></div>
                  </div>
                </div>

                <div
                  role="status"
                  aria-live="polite"
                  aria-atomic="true"
                  className={`absolute left-1/2 top-4 w-[min(92%,30rem)] -translate-x-1/2 rounded-2xl border px-4 py-2.5 text-center text-sm font-medium shadow-lg backdrop-blur transition-colors duration-200 sm:top-5 ${statusBannerClass}`}
                >
                  <div>{guidanceMessage}</div>
                </div>

              </div>
            )}
          </>
        )}

        <canvas ref={canvasRef} className="hidden" />
        <canvas ref={analysisCanvasRef} className="hidden" />
      </div>

      <PassportCameraFooter camera={camera} />
    </div>
  );
}

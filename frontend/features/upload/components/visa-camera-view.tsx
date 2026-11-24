"use client";

import { useRef } from "react";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { type VisaCameraController } from "../hooks/use-visa-camera";
import { X, AlertTriangle, Loader2 } from "lucide-react";
import { ACTIVE_VISA_CAMERA_PROFILE } from "./visa-camera.constants";
import Image from "next/image";
import { VisaCameraFooter } from "./visa-camera-footer";

export function VisaCameraView({ camera }: { camera: VisaCameraController }) {
  const {
    videoRef, guideRef, captureCanvasRef, analysisCanvasRef, lastAnalysisRef, setIsCameraReady,
    mirrorPreview, cameraError, capturedPreview, isProcessing, processingError, close,
    retryCamera, ready, guidance,
  } = camera;

  const dialogRef = useRef<HTMLDivElement>(null);

  const handleKeyDown = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: true, onClose: close });

  return (
    <div
      ref={dialogRef}
      onKeyDown={handleKeyDown}
      role="dialog"
      aria-modal="true"
      aria-labelledby="visa-photo-camera-title"
      className="fixed inset-0 z-50 flex h-[100dvh] min-h-0 flex-col overflow-hidden bg-slate-50 text-slate-900"
    >
      <header className="z-10 flex min-h-[4.5rem] flex-none items-center justify-between border-b border-slate-200 bg-white px-4 pb-3 pt-[max(0.75rem,env(safe-area-inset-top))] shadow-sm">
        <button type="button" onClick={close} aria-label="Close Visa Photo camera" className="rounded-full border border-slate-200 bg-white p-2 text-slate-600 shadow-sm transition-colors hover:bg-slate-50 hover:text-slate-900">
          <X className="h-6 w-6" />
        </button>
        <div className="text-center">
          <h2 id="visa-photo-camera-title" className="text-base font-semibold text-slate-950">
            Visa Photo Upload
          </h2>
          <p className="text-xs text-slate-500">
            {ACTIVE_VISA_CAMERA_PROFILE === "relaxed"
              ? "Use one face and a plain white or off-white wall"
              : "Remove glasses, keep eyes open, and use a plain light wall"}
          </p>
        </div>
        <div className="w-10" aria-hidden="true" />
      </header>

      <main className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-slate-100">
        {cameraError ? (
          <div
            role="alert"
            className="mx-6 max-w-md rounded-2xl border border-amber-200 bg-white p-6 text-center shadow-xl"
          >
            <AlertTriangle className="mx-auto mb-4 h-10 w-10 text-amber-500" aria-hidden="true" />
            <h3 className="mb-2 text-lg font-semibold text-slate-950">Camera unavailable</h3>
            <p className="mb-6 text-sm leading-6 text-slate-600">{cameraError}</p>
            <div className="flex flex-col gap-3">
              <Button onClick={retryCamera} className="w-full">Retry camera</Button>
              <Button variant="outline" onClick={close} className="w-full border-slate-300 bg-white text-slate-700 hover:bg-slate-50">Back</Button>
            </div>
          </div>
        ) : (
          <>
            <video
              ref={videoRef}
              autoPlay
              muted
              playsInline
              onLoadedData={() => {
                lastAnalysisRef.current = performance.now();
                setIsCameraReady(true);
              }}
              className={`h-full w-full object-cover ${mirrorPreview ? "scale-x-[-1]" : ""} ${capturedPreview ? "opacity-0" : "opacity-100"}`}
            />
            {capturedPreview ? (
              <Image src={capturedPreview} alt="Captured Visa Photo" fill unoptimized className="bg-slate-100 object-contain" />
            ) : (
              <div className="pointer-events-none absolute inset-0">
                {/* The outer frame is a familiar portrait-placement guide. The
                    invisible inner element keeps the exact central 2:3 area
                    used for live analysis and the final 800x1200 capture. */}
                <div
                  data-testid="visa-photo-placement-guide"
                  className="absolute bottom-[clamp(0.75rem,1.75dvh,1.25rem)] left-1/2 aspect-[35/45] w-[72vw] max-w-[26rem] -translate-x-1/2"
                  style={{ width: "min(72vw, 42dvh, 26rem)" }}
                >
                  <div className={`absolute inset-0 rounded-[1.75rem] border-[3px] shadow-[0_0_0_9999px_rgba(248,250,252,0.42)] transition-colors ${ready ? "border-emerald-500" : "border-white"}`} />
                  <div
                    ref={guideRef}
                    data-testid="visa-photo-output-crop"
                    className="absolute left-1/2 top-0 h-full w-[85.7143%] aspect-[2/3] -translate-x-1/2"
                  >
                    <svg
                      aria-hidden="true"
                      viewBox="0 0 100 126"
                      className="absolute inset-x-[4%] bottom-[15%] h-[88%] w-[92%]"
                      preserveAspectRatio="xMidYMax meet"
                    >
                      <path
                        d="M50 3 C32 3 22 19 22 41 C22 59 28 73 38 80 L38 87 C20 89 8 99 5 126 L95 126 C92 99 80 89 62 87 L62 80 C72 73 78 59 78 41 C78 19 68 3 50 3 Z"
                        fill="none"
                        strokeWidth="1.7"
                        strokeDasharray="4 3"
                        vectorEffect="non-scaling-stroke"
                        className={`transition-colors ${ready ? "stroke-emerald-500" : "stroke-white"}`}
                      />
                    </svg>
                  </div>
                </div>
                <div
                  role={processingError ? "alert" : "status"}
                  aria-live={processingError ? "assertive" : "polite"}
                  aria-atomic="true"
                  className={`absolute left-1/2 top-2 w-max max-w-[92%] -translate-x-1/2 rounded-full border px-4 py-2 text-center text-sm font-medium shadow-lg backdrop-blur-md ${processingError ? "border-red-500 bg-red-600 text-white" : ready ? "border-emerald-500 bg-emerald-500 text-white" : "border-slate-200/80 bg-white/90 text-slate-800"}`}
                >
                  {guidance}
                </div>
              </div>
            )}
            {isProcessing && (
              <div
                role="status"
                aria-live="polite"
                className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-3 bg-white/90 px-6 text-center text-slate-900 backdrop-blur-sm"
              >
                <Loader2 className="h-9 w-9 animate-spin text-blue-600" aria-hidden="true" />
                <p className="text-sm font-medium">Saving your Visa Photo</p>
              </div>
            )}
          </>
        )}
        <canvas ref={captureCanvasRef} className="hidden" />
        <canvas ref={analysisCanvasRef} className="hidden" />
      </main>

      <VisaCameraFooter camera={camera} />
    </div>
  );
}

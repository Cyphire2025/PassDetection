"use client";

import Image from "next/image";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  FileImage,
  Loader2,
  RefreshCcw,
  ShieldCheck,
  Upload,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import type { VisaPhotoRejectionReason } from "../services/public-flow-telemetry";
import {
  uploadedVisaPhotoFailureMessage,
  verifyUploadedVisaPhoto,
  VISA_PHOTO_UPLOAD_ACCEPT,
  visaPhotoUploadRejectionReason,
} from "../services/visa-photo-upload-validation";

interface VisaPhotoUploadProps {
  onCapture: (file: File) => void;
  onCancel: () => void;
  onTelemetryReason?: (reason: VisaPhotoRejectionReason) => void;
}

type UploadStatus = "idle" | "checking" | "passed" | "failed";

export function VisaPhotoUpload({
  onCapture,
  onCancel,
  onTelemetryReason = () => undefined,
}: VisaPhotoUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const previewUrlRef = useRef<string | null>(null);
  const validationRunRef = useRef(0);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [selectedName, setSelectedName] = useState("");
  const [verifiedFile, setVerifiedFile] = useState<File | null>(null);
  const [status, setStatus] = useState<UploadStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  const replacePreview = useCallback((file: File) => {
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    const nextUrl = URL.createObjectURL(file);
    previewUrlRef.current = nextUrl;
    setPreviewUrl(nextUrl);
  }, []);

  useEffect(() => () => {
    validationRunRef.current += 1;
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
  }, []);

  const chooseFile = () => inputRef.current?.click();

  const handleFile = async (file: File) => {
    const runId = validationRunRef.current + 1;
    validationRunRef.current = runId;
    setSelectedName(file.name);
    setVerifiedFile(null);
    setError(null);
    setStatus("checking");
    replacePreview(file);
    try {
      const result = await verifyUploadedVisaPhoto(file);
      if (validationRunRef.current !== runId) return;
      if (result.validation.outcome !== "pass") {
        const reason = visaPhotoUploadRejectionReason(result.validation);
        if (reason) onTelemetryReason(reason);
        setStatus("failed");
        setError(uploadedVisaPhotoFailureMessage(result.validation));
        return;
      }
      replacePreview(result.file);
      setVerifiedFile(result.file);
      setStatus("passed");
    } catch (validationError) {
      if (validationRunRef.current !== runId) return;
      const message = validationError instanceof Error
        ? validationError.message
        : "The selected Visa Photo could not be verified. Try again or use the live camera.";
      setStatus("failed");
      setError(message);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="visa-photo-upload-title"
      className="fixed inset-0 z-50 flex h-[100dvh] min-h-0 flex-col overflow-hidden bg-slate-50 text-slate-900"
    >
      <header className="z-10 flex min-h-[4.5rem] flex-none items-center justify-between border-b border-slate-200 bg-white px-4 pb-3 pt-[max(0.75rem,env(safe-area-inset-top))] shadow-sm">
        <button
          type="button"
          onClick={onCancel}
          aria-label="Close Visa Photo upload"
          className="flex h-11 w-11 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-600 shadow-sm transition hover:bg-slate-50"
        >
          <X className="h-6 w-6" />
        </button>
        <div className="px-3 text-center">
          <h1 id="visa-photo-upload-title" className="text-lg font-bold text-slate-950">
            Upload Studio Visa Photo
          </h1>
          <p className="mt-0.5 text-xs text-slate-500">
            The background is checked before the photo can be used
          </p>
        </div>
        <div className="h-11 w-11" aria-hidden="true" />
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:py-8">
        <div className="mx-auto w-full max-w-xl space-y-4">
          <div className="rounded-2xl border border-amber-300 bg-amber-50 p-4 text-amber-950 shadow-sm">
            <div className="flex gap-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-700" aria-hidden="true" />
              <p className="text-sm leading-6">
                Upload only a studio-taken photo with a plain white background.
              </p>
            </div>
          </div>

          <input
            ref={inputRef}
            type="file"
            accept={VISA_PHOTO_UPLOAD_ACCEPT}
            className="sr-only"
            aria-label="Choose a studio Visa Photo"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) void handleFile(file);
            }}
          />

          <section className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
            <div className="relative mx-auto aspect-[2/3] w-full max-w-sm overflow-hidden bg-slate-100">
              {previewUrl ? (
                <Image
                  src={previewUrl}
                  alt="Selected Visa Photo preview"
                  fill
                  unoptimized
                  sizes="(max-width: 640px) 100vw, 384px"
                  className="object-cover"
                />
              ) : (
                <div className="flex h-full flex-col items-center justify-center gap-3 px-8 text-center text-slate-500">
                  <span className="flex h-16 w-16 items-center justify-center rounded-2xl bg-blue-50 text-blue-600">
                    <FileImage className="h-8 w-8" aria-hidden="true" />
                  </span>
                  <p className="text-sm leading-6">
                    Choose the original digital file supplied by the studio.
                  </p>
                </div>
              )}
              {status === "checking" && (
                <div
                  role="status"
                  aria-live="polite"
                  className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-slate-950/65 px-6 text-center text-white backdrop-blur-sm"
                >
                  <Loader2 className="h-10 w-10 animate-spin" aria-hidden="true" />
                  <div>
                    <p className="font-bold">Verifying Visa Photo</p>
                    <p className="mt-1 text-xs leading-5 text-slate-200">
                      Checking for a white or off-white background. This usually takes 1–2 seconds.
                    </p>
                  </div>
                </div>
              )}
              {status === "passed" && (
                <div className="absolute bottom-3 left-3 right-3 flex items-center gap-2 rounded-xl bg-emerald-600 px-3 py-2 text-sm font-semibold text-white shadow-lg">
                  <ShieldCheck className="h-5 w-5 shrink-0" aria-hidden="true" />
                  White background check passed
                </div>
              )}
            </div>

            <div className="space-y-4 border-t border-slate-100 p-4 sm:p-5">
              {selectedName && (
                <p className="truncate text-xs text-slate-500" title={selectedName}>
                  Selected: {selectedName}
                </p>
              )}
              {error && (
                <div role="alert" className="flex gap-3 rounded-xl border border-red-200 bg-red-50 p-3 text-red-950">
                  <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-red-600" aria-hidden="true" />
                  <p className="text-sm leading-5">{error}</p>
                </div>
              )}
              <div className="flex flex-col gap-3 sm:flex-row">
                <Button
                  type="button"
                  variant="outline"
                  size="lg"
                  onClick={chooseFile}
                  disabled={status === "checking"}
                  className="flex-1 border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
                >
                  {previewUrl ? <RefreshCcw className="h-4 w-4" /> : <Upload className="h-4 w-4" />}
                  {previewUrl ? "Choose another" : "Choose studio photo"}
                </Button>
                {verifiedFile && (
                  <Button
                    type="button"
                    size="lg"
                    onClick={() => onCapture(verifiedFile)}
                    className="flex-1 bg-blue-600 hover:bg-blue-700"
                  >
                    <Check className="h-4 w-4" /> Use Visa Photo
                  </Button>
                )}
              </div>
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}

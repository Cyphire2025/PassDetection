"use client";

import Image from "next/image";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  FileImage,
  Loader2,
  RefreshCcw,
  Upload,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { VisaPhotoSample } from "./visa-photo-sample";
import { VisaPhotoGuidelines } from "./visa-photo-guidelines";
import { InstructionLanguageSelector } from "./instruction-language-selector";
import { UPLOAD_INSTRUCTIONS } from "../config/instruction-translations";
import type { InstructionLanguageControl } from "../hooks/use-instruction-language";
import { preparePublicUploadFile, PUBLIC_UPLOAD_ACCEPT } from "../services/public-upload-file";
import { errorMessage } from "../services/upload-flow-helpers";

interface VisaPhotoUploadProps {
  token?: string;
  uploadSessionId?: string;
  onCapture: (file: File) => void;
  onCancel: () => void;
  instructions?: InstructionLanguageControl;
}

type UploadStatus = "idle" | "preparing" | "ready" | "failed";

export function VisaPhotoUpload({
  token,
  uploadSessionId,
  onCapture,
  onCancel,
  instructions,
}: VisaPhotoUploadProps) {
  const language = instructions?.language ?? "en";
  const inputRef = useRef<HTMLInputElement>(null);
  const previewCardRef = useRef<HTMLDivElement>(null);
  const previewUrlRef = useRef<string | null>(null);
  const preparationRunRef = useRef(0);
  const preparationRef = useRef<AbortController | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [selectedName, setSelectedName] = useState("");
  const [preparedFile, setPreparedFile] = useState<File | null>(null);
  const [status, setStatus] = useState<UploadStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const handleKeyDown = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: true, onClose: onCancel });
  const hasSelection = Boolean(selectedName);
  const isPreparing = status === "preparing";

  useEffect(() => {
    if (hasSelection) previewCardRef.current?.focus({ preventScroll: true });
  }, [hasSelection]);

  const replacePreview = useCallback((file: File) => {
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    const nextUrl = URL.createObjectURL(file);
    previewUrlRef.current = nextUrl;
    setPreviewUrl(nextUrl);
  }, []);

  useEffect(() => {
    return () => {
      preparationRunRef.current += 1;
      preparationRef.current?.abort();
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    };
  }, []);

  const chooseFile = () => inputRef.current?.click();

  const handleFile = async (file: File) => {
    const runId = preparationRunRef.current + 1;
    preparationRunRef.current = runId;
    preparationRef.current?.abort();
    const preparation = new AbortController();
    preparationRef.current = preparation;
    setSelectedName(file.name);
    setPreparedFile(null);
    setError(null);
    setStatus("preparing");
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    previewUrlRef.current = null;
    setPreviewUrl(null);
    try {
      const previewFile = await preparePublicUploadFile(file, {
        token, uploadSessionId, purpose: "visa", signal: preparation.signal,
      });
      if (preparationRunRef.current !== runId) return;
      replacePreview(previewFile);
      setPreparedFile(previewFile);
      setStatus("ready");
    } catch (preparationError) {
      if (preparationRunRef.current !== runId) return;
      const message = errorMessage(preparationError,
        "The selected file preview could not be prepared. Please try again or choose another file.");
      setStatus("failed");
      setError(message);
    }
  };

  return (
    <div
      ref={dialogRef}
      onKeyDown={handleKeyDown}
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
            Preview your uploaded photo or PDF before continuing
          </p>
        </div>
        <div className="h-11 w-11" aria-hidden="true" />
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:py-8">
        <div className="mx-auto w-full max-w-3xl space-y-4">
          <div className="flex justify-end"><InstructionLanguageSelector instructions={instructions} /></div>
          <div className="rounded-2xl border border-amber-300 bg-amber-50 p-4 text-amber-950 shadow-sm">
            <div className="flex gap-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-700" aria-hidden="true" />
              <p lang={language} dir={language === "ur" ? "rtl" : "ltr"} className="text-sm leading-6">
                {UPLOAD_INSTRUCTIONS[language].visaWarning}
              </p>
            </div>
          </div>

          <input
            ref={inputRef}
            type="file"
            accept={PUBLIC_UPLOAD_ACCEPT}
            className="sr-only"
            aria-label="Choose a studio Visa Photo"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) void handleFile(file);
            }}
          />

          <section className="grid items-start gap-5 overflow-hidden rounded-3xl border border-slate-200 bg-white p-4 shadow-sm sm:grid-cols-[220px_minmax(0,1fr)] sm:p-5">
            <VisaPhotoGuidelines language={language} />
            <VisaPhotoSample />
            <div className="min-w-0 space-y-4">
              {hasSelection ? (
                <div
                  ref={previewCardRef}
                  role="group"
                  aria-label="Selected Visa Photo"
                  tabIndex={-1}
                  className="overflow-hidden rounded-2xl border border-slate-200 bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:ring-offset-2"
                >
                  <div className="border-b border-slate-200 bg-white px-4 py-3">
                    <p className="text-sm font-semibold text-slate-800">Your selected photo</p>
                  </div>
                  <div className="relative p-4">
                    <div className="relative mx-auto h-[300px] w-[220px] max-w-full overflow-hidden rounded-lg bg-white shadow-sm ring-1 ring-slate-200">
                      {previewUrl ? <Image
                        src={previewUrl}
                        alt="Selected Visa Photo preview"
                        fill
                        unoptimized
                        sizes="220px"
                        className="object-contain"
                      /> : <div className="flex h-full items-center justify-center px-4 text-center text-sm leading-6 text-slate-500">{status === "failed" ? "Choose another file to see its preview here." : "Preparing your preview…"}</div>}
                    </div>
                    {isPreparing && (
                      <div
                        role="status"
                        aria-live="polite"
                        className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-white/95 px-6 text-center text-slate-900 backdrop-blur-sm"
                      >
                        <Loader2 className="h-9 w-9 animate-spin text-teal-700" aria-hidden="true" />
                        <div>
                          <p className="font-semibold">Preparing photo preview</p>
                          <p className="mt-2 text-sm leading-6 text-slate-600">
                            Preparing a clear preview. PDFs must contain exactly one page.
                          </p>
                        </div>
                      </div>
                    )}
                  </div>
                  <div className="flex min-w-0 items-center gap-2 border-t border-slate-200 bg-white px-4 py-3">
                    <FileImage className="h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
                    <p className="min-w-0 truncate text-xs text-slate-600" title={selectedName}>Selected: {selectedName}</p>
                  </div>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={chooseFile}
                  aria-label="Choose studio photo"
                  className="group flex min-h-[340px] w-full flex-col items-center justify-center rounded-2xl border-2 border-dashed border-teal-200 bg-teal-50/40 px-5 py-7 text-center transition-colors hover:border-teal-500 hover:bg-teal-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:ring-offset-4"
                >
                  <span className="mb-5 flex h-16 w-16 items-center justify-center rounded-2xl border border-teal-100 bg-white text-teal-700 shadow-sm transition-colors group-hover:border-teal-300">
                    <Upload className="h-7 w-7" aria-hidden="true" />
                  </span>
                  <span className="text-base font-semibold text-slate-900">Add your studio photo</span>
                  <span className="mt-2 max-w-[28ch] text-sm leading-6 text-slate-600">
                    Choose the original digital photo provided by your studio.
                  </span>
                  <span className="mt-5 inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-teal-700 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors group-hover:bg-teal-800">
                    <FileImage className="h-4 w-4" aria-hidden="true" />
                    Choose studio photo
                  </span>
                  <span className="mt-4 text-xs leading-5 text-slate-500">
                    JPG/JPEG, PNG, HEIC/HEIF, AVIF or PDF
                    <span className="block">Images up to 10 MB · PDFs up to 2 MB</span>
                    <span className="block">PDFs must contain exactly 1 page</span>
                  </span>
                </button>
              )}

              {error && (
                <div role="alert" className="flex gap-3 rounded-xl border border-red-200 bg-red-50 p-3 text-red-950">
                  <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-red-600" aria-hidden="true" />
                  <p className="text-sm leading-6">{error}</p>
                </div>
              )}
              {hasSelection && (
                <div className="flex flex-col gap-3 sm:flex-row">
                  <Button
                    type="button"
                    variant="outline"
                    size="lg"
                    onClick={chooseFile}
                    disabled={isPreparing}
                    className="min-h-11 flex-1 rounded-xl border-slate-300 bg-white text-sm text-slate-700 hover:bg-slate-50"
                  >
                    <RefreshCcw className="h-4 w-4" /> Choose another
                  </Button>
                  {preparedFile && (
                    <Button
                      type="button"
                      size="lg"
                      onClick={() => onCapture(preparedFile)}
                      className="min-h-11 flex-1 rounded-xl bg-teal-700 text-sm hover:bg-teal-800 focus-visible:ring-teal-600"
                    >
                      <Check className="h-4 w-4" /> Use Visa Photo
                    </Button>
                  )}
                </div>
              )}
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}

import type { ReactNode } from "react";
import {
  BadgeCheck,
  Camera,
  CheckCircle2,
  ChevronRight,
  ImagePlus,
  Loader2,
  User,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { formatFileSize } from "../services/upload-flow-helpers";
import { PASSPORT_IMAGE_ACCEPT } from "./upload-flow.constants";
import type { PassportDocumentBundle } from "./upload-flow.types";

export function VisaSelfieChoice({
  file,
  onCameraClick,
  onUploadClick,
}: {
  file: File | null;
  onCameraClick: () => void;
  onUploadClick: () => void;
}) {
  return (
    <section
      data-testid="visa-photo-choice"
      className="relative rounded-2xl border-2 border-slate-100 bg-white p-4 shadow-sm sm:p-5"
    >
      <div className="flex items-start gap-3 pr-20 sm:gap-4">
        <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl sm:h-12 sm:w-12 ${
          file ? "bg-emerald-100 text-emerald-700" : "bg-blue-100 text-blue-600"
        }`}>
          {file ? <CheckCircle2 className="h-6 w-6" /> : <User className="h-6 w-6" />}
        </div>
        <div className="min-w-0">
          <h4 className="text-base font-bold text-slate-900">
            {file ? "Visa Photo ready" : "Upload Photo for Visa"}
          </h4>
          <p className="mt-1 text-sm leading-5 text-slate-500">
            {file
              ? "The selected Visa Photo passed the required checks. You can replace it using either option below."
              : "Required. Choose live capture or upload the original digital photo supplied by a studio."}
          </p>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <Button
          type="button"
          variant="outline"
          onClick={onCameraClick}
          className="h-11 border-blue-200 bg-blue-50 text-blue-800 hover:border-blue-300 hover:bg-blue-100"
        >
          <Camera className="h-4 w-4" />
          Use live camera
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={onUploadClick}
          className="h-11 border-blue-200 bg-white text-blue-800 hover:border-blue-300 hover:bg-blue-50"
        >
          <ImagePlus className="h-4 w-4" />
          Upload studio photo
        </Button>
      </div>

      <div className="mt-3 rounded-xl border border-amber-300 bg-amber-50 px-3 py-2.5 text-xs leading-5 text-amber-950">
        Upload only a studio-taken photo with a plain white background.
      </div>

      <span className={`pointer-events-none absolute right-3 top-3 rounded-full px-2.5 py-1 text-[11px] font-bold ${
        file ? "bg-emerald-100 text-emerald-700" : "bg-blue-100 text-blue-700"
      }`}>
        {file ? "Completed" : "Required"}
      </span>
    </section>
  );
}

export function PassportUploadSection({
  children,
  allowFilesFromDevice,
}: {
  children: ReactNode;
  allowFilesFromDevice: boolean;
}) {
  return (
    <details className="group overflow-hidden rounded-2xl border-2 border-slate-100 bg-white shadow-sm" open>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-4 marker:hidden sm:p-5">
        <div>
          <h4 className="text-base font-bold text-slate-900">Passport</h4>
          <p className="mt-1 text-sm text-slate-500">
            {allowFilesFromDevice
              ? "Scan both passport pages live or choose existing images from this device."
              : "Live scanning is mandatory for both passport pages in this group."}
          </p>
        </div>
        <ChevronRight className="h-5 w-5 shrink-0 text-slate-400 transition-transform group-open:rotate-90" />
      </summary>
      <div className="border-t border-slate-100 p-4 pt-4 sm:p-5">
        <div className="space-y-4">{children}</div>
      </div>
    </details>
  );
}

export function PassportDocumentBundlePanel({
  bundle,
  allowFilesFromDevice,
  onChange,
  onScan,
  onFileSelect,
  onUpload,
}: {
  bundle: PassportDocumentBundle;
  allowFilesFromDevice: boolean;
  onChange: (bundle: PassportDocumentBundle) => void;
  onScan: (pageSide: "front" | "back") => void;
  onFileSelect: (pageSide: "front" | "back", file: File) => void;
  onUpload: () => void;
}) {
  const updateFile = (pageSide: "front" | "back", file: File | null) => {
    if (file) {
      onFileSelect(pageSide, file);
      return;
    }
    onChange(pageSide === "front"
      ? {
          ...bundle,
          front: null,
          frontSource: null,
          frontManuallyCropped: false,
        }
      : {
          ...bundle,
          back: null,
          backSource: null,
          backManuallyCropped: false,
        });
  };
  const readyPageCount = Number(Boolean(bundle.front)) + Number(Boolean(bundle.back));

  return (
    <div className="rounded-3xl border border-slate-200 bg-gradient-to-b from-white to-slate-50/70 p-3 shadow-sm sm:p-5">
      <div className="mb-5 flex items-start gap-3 px-1">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-blue-50 text-blue-700 ring-1 ring-blue-100 sm:h-12 sm:w-12">
          <Camera className="h-6 w-6" />
        </div>
        <div className="min-w-0">
          <h4 className="text-base font-bold text-slate-900">Capture both passport pages</h4>
          <p className="mt-1 text-sm leading-5 text-slate-500">
            Add a clear front and back image. We will read the details after both pages are saved.
          </p>
        </div>
      </div>

      <div
        className="grid gap-3"
        style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 18rem), 1fr))" }}
      >
        <PassportPageCaptureControl
          pageSide="front"
          file={bundle.front}
          source={bundle.frontSource}
          allowFilesFromDevice={allowFilesFromDevice}
          onScan={() => onScan("front")}
          onFileChange={(file) => updateFile("front", file)}
        />
        <PassportPageCaptureControl
          pageSide="back"
          file={bundle.back}
          source={bundle.backSource}
          allowFilesFromDevice={allowFilesFromDevice}
          onScan={() => onScan("back")}
          onFileChange={(file) => updateFile("back", file)}
        />
      </div>
      <div className="mt-4 flex items-center justify-between gap-3 px-1 text-xs">
        <span className="font-medium text-slate-500" aria-live="polite">
          {readyPageCount} of 2 pages ready
        </span>
        <span className={readyPageCount === 2 ? "font-semibold text-emerald-700" : "text-slate-400"}>
          {readyPageCount === 2 ? "Ready to extract" : "Both pages required"}
        </span>
      </div>
      <Button
        type="button"
        className="mt-3 h-12 w-full rounded-xl bg-blue-600 font-semibold shadow-lg shadow-blue-600/15 hover:bg-blue-700"
        onClick={onUpload}
        disabled={!bundle.front || !bundle.back}
      >
        <BadgeCheck className="h-5 w-5" aria-hidden="true" />
        Save pages &amp; extract details
      </Button>
      <p className="mt-3 px-1 text-center text-xs leading-5 text-slate-400">
        Reading usually takes about 30–35 seconds. Keep this page open while we verify the details.
      </p>
    </div>
  );
}

export function SavedPassportActions({
  onResume,
  onReplace,
  isReplacing,
}: {
  onResume: () => void;
  onReplace: () => void;
  isReplacing: boolean;
}) {
  return (
    <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
      <div className="flex items-start gap-3">
        <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-700" />
        <div>
          <h4 className="text-sm font-bold text-emerald-950">Passport pages saved</h4>
          <p className="mt-1 text-sm leading-5 text-emerald-800">
            Continue reviewing the saved images. Replacing them is an explicit action, so back-navigation will not discard a successful upload.
          </p>
        </div>
      </div>
      <div className="mt-4 grid gap-2 sm:grid-cols-2">
        <Button type="button" onClick={onResume} disabled={isReplacing}>
          Resume review
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={onReplace}
          disabled={isReplacing}
          aria-busy={isReplacing}
        >
          {isReplacing && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />}
          {isReplacing ? "Replacing saved pages" : "Replace saved pages"}
        </Button>
      </div>
    </div>
  );
}

function PassportPageCaptureControl({
  pageSide,
  file,
  source,
  allowFilesFromDevice,
  onScan,
  onFileChange,
}: {
  pageSide: "front" | "back";
  file: File | null;
  source: "camera" | "file" | null;
  allowFilesFromDevice: boolean;
  onScan: () => void;
  onFileChange: (file: File | null) => void;
}) {
  const label = `Passport ${pageSide} page`;
  const inputId = `passport-${pageSide}-file`;
  const pageNumber = pageSide === "front" ? 1 : 2;

  return (
    <section
      aria-labelledby={`${inputId}-label`}
      className={`rounded-2xl border p-4 transition ${
        file
          ? "border-emerald-200 bg-emerald-50/40 shadow-sm"
          : "border-slate-200 bg-white"
      }`}
    >
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
            file ? "bg-emerald-600 text-white" : "bg-slate-100 text-slate-600"
          }`}>
            {file ? <CheckCircle2 className="h-4 w-4" aria-hidden="true" /> : pageNumber}
          </span>
          <div className="min-w-0">
            <h5 id={`${inputId}-label`} className="text-sm font-bold text-slate-900">{label}</h5>
            <p id={`${inputId}-hint`} className="mt-1 text-xs leading-5 text-slate-500">
              {pageSide === "front"
                ? "Open the photo and MRZ details page."
                : "Add the opposite passport page for the agency record."}
            </p>
          </div>
        </div>
        <span className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-bold ${
          file ? "bg-emerald-100 text-emerald-800" : "bg-amber-50 text-amber-700"
        }`}>
          {file ? "Ready" : "Required"}
        </span>
      </div>

      {file ? (
        <div className="mb-3 flex min-w-0 items-center gap-3 rounded-xl border border-emerald-200 bg-white p-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-50 text-emerald-700">
            <ImagePlus className="h-5 w-5" aria-hidden="true" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-semibold text-slate-800" title={file.name}>
              {file.name}
            </span>
            <span className="mt-0.5 block text-xs text-slate-500">
              {source === "camera" ? "Live camera scan" : "Selected from device"} · {formatFileSize(file.size)}
            </span>
          </span>
          <button
            type="button"
            onClick={() => onFileChange(null)}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-slate-400 transition hover:bg-red-50 hover:text-red-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            aria-label={`Remove ${label.toLowerCase()}`}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      ) : (
        <div className="mb-3 flex min-h-20 items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 text-center">
          <p className="text-xs leading-5 text-slate-500">No {pageSide} page selected yet</p>
        </div>
      )}

      <div className={`grid gap-2 ${allowFilesFromDevice ? "min-[360px]:grid-cols-2" : ""}`}>
        <Button
          type="button"
          variant={file && source === "camera" ? "secondary" : "outline"}
          className="h-11 w-full rounded-xl"
          onClick={onScan}
          aria-label={`${file && source === "camera" ? "Retake" : "Scan"} passport ${pageSide} page with live camera`}
        >
          <Camera className="h-4 w-4" aria-hidden="true" />
          {file && source === "camera" ? "Retake scan" : "Use camera"}
        </Button>

        {allowFilesFromDevice && (
          <>
            <label
              htmlFor={inputId}
              className="inline-flex h-11 cursor-pointer items-center justify-center gap-2 rounded-xl border border-blue-200 bg-blue-50 px-3 text-sm font-semibold text-blue-700 transition hover:border-blue-300 hover:bg-blue-100 focus-within:ring-2 focus-within:ring-blue-500 focus-within:ring-offset-2"
            >
              <ImagePlus className="h-4 w-4" aria-hidden="true" />
              {file && source === "file" ? "Choose another" : "Choose photo"}
            </label>
            <input
              key={`${pageSide}:${source ?? "empty"}:${file?.name ?? ""}`}
              id={inputId}
              type="file"
              accept={PASSPORT_IMAGE_ACCEPT}
              className="sr-only"
              onClick={(event) => {
                event.currentTarget.value = "";
              }}
              onChange={(event) => onFileChange(event.target.files?.[0] ?? null)}
              aria-describedby={`${inputId}-hint ${inputId}-formats`}
              aria-label={`Choose passport ${pageSide} page image from device`}
            />
          </>
        )}
      </div>

      {allowFilesFromDevice && (
        <p id={`${inputId}-formats`} className="mt-3 text-xs leading-5 text-slate-400">
          JPG, PNG, WebP, HEIC/HEIF, AVIF, BMP, or TIFF
        </p>
      )}
    </section>
  );
}

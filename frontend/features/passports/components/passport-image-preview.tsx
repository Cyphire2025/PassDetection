"use client";

import { useRef } from "react";
import { ExternalLink, Loader2, Pencil, Upload } from "lucide-react";
import type { PassportImageType } from "../api/passports.api";
import { PASSPORT_LIBRARY_IMAGE_ACCEPT } from "../utils/passport-image-library";
import { CompactPassportImage } from "./compact-passport-image";

export function PassportImagePreview({
  label,
  imageType,
  url,
  clientName,
  revision,
  canCrop,
  canChange,
  changeDisabled,
  isChanging,
  changeError,
  onChange,
  onCrop,
}: {
  label: string;
  imageType: PassportImageType;
  url?: string | null;
  clientName: string;
  revision: number;
  canCrop: boolean;
  canChange: boolean;
  changeDisabled: boolean;
  isChanging: boolean;
  changeError?: string;
  onChange: (file: File) => void;
  onCrop: (trigger: HTMLButtonElement) => void;
}) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const effectiveUrl = url ? appendCacheRevision(url, revision) : null;
  return (
    <section>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-700">{label}</h3>
        {(effectiveUrl || canChange) && (
          <div className="flex items-center gap-2">
            {effectiveUrl && (
              <a
                href={effectiveUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              >
                <ExternalLink className="h-3.5 w-3.5" /> Open
              </a>
            )}
            {canChange && (
              <>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept={PASSPORT_LIBRARY_IMAGE_ACCEPT}
                  aria-label={`Choose a replacement ${label} image`}
                  className="sr-only"
                  disabled={changeDisabled}
                  onChange={(event) => {
                    const selected = event.currentTarget.files?.[0];
                    event.currentTarget.value = "";
                    if (selected) onChange(selected);
                  }}
                />
                <button
                  type="button"
                  disabled={changeDisabled}
                  aria-busy={isChanging}
                  onClick={() => fileInputRef.current?.click()}
                  className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-blue-700 shadow-sm hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isChanging ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                  ) : (
                    <Upload className="h-3.5 w-3.5" aria-hidden="true" />
                  )}
                  {isChanging ? "Changing…" : "Change"}
                </button>
              </>
            )}
            {effectiveUrl && canCrop && (
              <button
                type="button"
                onClick={(event) => onCrop(event.currentTarget)}
                data-image-type={imageType}
                className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-blue-700 shadow-sm hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              >
                <Pencil className="h-3.5 w-3.5" /> Edit
              </button>
            )}
          </div>
        )}
      </div>
      {changeError && (
        <p role="alert" className="mb-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {changeError}
        </p>
      )}
      {effectiveUrl ? (
        <a
          href={effectiveUrl}
          target="_blank"
          rel="noreferrer"
          aria-label={`Open ${label} for ${clientName} in a new tab`}
          className="inline-block max-w-full overflow-hidden rounded-xl bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
        >
          <CompactPassportImage src={effectiveUrl} alt={`${label} for ${clientName}`} />
        </a>
      ) : (
        <div className="flex min-h-32 items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 text-sm text-slate-400">
          Not uploaded
        </div>
      )}
    </section>
  );
}

function appendCacheRevision(url: string, revision: number) {
  if (revision === 0) return url;
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}ui_crop_revision=${revision}`;
}

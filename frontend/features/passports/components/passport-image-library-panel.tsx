"use client";

import { useRef } from "react";
import { Check, Images, Loader2, Upload } from "lucide-react";
import { Button } from "@/components/ui";
import type { PassportImageLibraryItem } from "../api/passports.api";
import { formatPassportImageLibrarySource, PASSPORT_LIBRARY_IMAGE_ACCEPT } from "../utils/passport-image-library";

export function ImageLibraryPanel({
  label,
  library,
  busy,
  isLoading,
  isUploading,
  usingImageId,
  onUpload,
  onUse,
}: {
  label: string;
  library: PassportImageLibraryItem[];
  busy: boolean;
  isLoading: boolean;
  isUploading: boolean;
  usingImageId: string | null;
  onUpload: (file: File) => void;
  onUse: (itemId: string) => void;
}) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  return (
    <section
      id="passport-image-library-panel"
      role="tabpanel"
      aria-labelledby="passport-image-library-title"
      className="flex min-h-[28rem] flex-1 flex-col rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3
            id="passport-image-library-title"
            className="flex items-center gap-2 text-base font-semibold text-slate-900"
          >
            <Images className="h-5 w-5 text-blue-600" aria-hidden="true" />
            Image library
          </h3>
          <p className="mt-1 max-w-2xl text-sm leading-5 text-slate-500">
            Choose any saved {label.toLowerCase()}, or upload a new image. The original image remains available if one was submitted.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">
            {library.length} saved
          </span>
          <input
            ref={fileInputRef}
            type="file"
            accept={PASSPORT_LIBRARY_IMAGE_ACCEPT}
            aria-label={`Upload a new ${label} image`}
            className="sr-only"
            disabled={busy}
            onChange={(event) => {
              const selected = event.currentTarget.files?.[0];
              event.currentTarget.value = "";
              if (selected) onUpload(selected);
            }}
          />
          <Button
            type="button"
            variant="outline"
            className="gap-2"
            disabled={busy}
            aria-busy={isUploading}
            onClick={() => fileInputRef.current?.click()}
          >
            {isUploading ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Upload className="h-4 w-4" aria-hidden="true" />
            )}
            {isUploading ? "Uploading…" : "Upload image"}
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div
          className="flex min-h-64 flex-1 items-center justify-center text-sm text-slate-500"
          role="status"
          aria-live="polite"
        >
          <Loader2 className="mr-2 h-5 w-5 animate-spin" aria-hidden="true" />
          Loading saved images
        </div>
      ) : library.length > 0 ? (
        <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {library.map((item) => {
            const sourceLabel = formatPassportImageLibrarySource(item.source);
            const savedAt = formatLibraryDate(item.created_at);
            const isUsing = usingImageId === item.id;
            return (
              <article
                key={item.id}
                className={`flex min-w-0 flex-col overflow-hidden rounded-xl border bg-white ${
                  item.is_current
                    ? "border-blue-400 ring-2 ring-blue-100"
                    : "border-slate-200"
                }`}
              >
                <div className="relative">
                  {/* Same-origin authorized endpoint; native lazy loading avoids eager library downloads. */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    loading="lazy"
                    src={item.image_url}
                    alt={`${sourceLabel} ${label}`}
                    className="h-48 w-full bg-slate-100 object-contain"
                  />
                  <span className={`absolute left-2 top-2 rounded-full px-2.5 py-1 text-[11px] font-semibold shadow-sm ${librarySourceBadgeClass(item.source)}`}>
                    {sourceLabel}
                  </span>
                  {item.is_current && (
                    <span className="absolute right-2 top-2 rounded-full bg-blue-600 px-2.5 py-1 text-[11px] font-semibold text-white shadow-sm">
                      In use
                    </span>
                  )}
                </div>
                <div className="flex flex-1 flex-col gap-2 p-3">
                  {savedAt && (
                    <p className="text-xs text-slate-500">{savedAt}</p>
                  )}
                  {item.source === "ai_generated" && item.prompt?.trim() && (
                    <p className="line-clamp-2 text-xs leading-5 text-slate-600" title={item.prompt}>
                      {item.prompt}
                    </p>
                  )}
                  <Button
                    type="button"
                    className="mt-auto w-full gap-2"
                    variant={item.is_current ? "secondary" : "primary"}
                    disabled={busy || item.is_current}
                    onClick={() => onUse(item.id)}
                  >
                    {isUsing ? (
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                    ) : (
                      <Check className="h-4 w-4" aria-hidden="true" />
                    )}
                    {item.is_current ? "Currently in use" : "Use this image"}
                  </Button>
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="mt-5 flex min-h-64 flex-1 items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50 px-6 text-center text-sm text-slate-500">
          No saved images are available for this slot yet. Upload an image to create the first library item.
        </div>
      )}
    </section>
  );
}

function librarySourceBadgeClass(
  source: PassportImageLibraryItem["source"],
): string {
  if (source === "original") return "bg-slate-900 text-white";
  if (source === "manual") return "bg-blue-600 text-white";
  return "bg-[#C8CE32] text-slate-950";
}

function formatLibraryDate(value: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString();
}


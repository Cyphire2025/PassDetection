"use client";

import { useEffect, useId, useRef, useState } from "react";
import { ImagePlus, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils/cn";
import type { ImageDraft } from "../api/branding-images.api";
import type { ImagePlacement } from "../image-crop";
import { ImagePositionEditor } from "./image-position-editor";

const MAX_IMAGE_BYTES = 8 * 1024 * 1024;
const ALLOWED_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

export function ImageUploadField({ kind, value, currentUrl, onChange, disabled = false, positioning }: {
  kind: "logo" | "banner" | "background"; value: ImageDraft; currentUrl?: string | null;
  onChange: (value: ImageDraft) => void; disabled?: boolean;
  positioning?: { value: ImagePlacement; onChange: (value: ImagePlacement) => void; aspect: number };
}) {
  const id = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string>();
  const [dragging, setDragging] = useState(false);
  const isLogo = kind === "logo";
  const label = isLogo ? "Company logo" : kind === "background" ? "Group background" : "Group banner";
  const localFile = value instanceof File ? value : null;
  const src = value === undefined ? currentUrl : null;
  const hasImage = Boolean(localFile || src);
  const imageClassName = cn("h-full w-full", isLogo ? "object-contain" : "object-cover");
  const choose = (file?: File) => {
    if (!file || disabled) return;
    if (!ALLOWED_TYPES.has(file.type)) { setError("Choose a JPG, PNG or WebP image."); return; }
    if (file.size > MAX_IMAGE_BYTES || file.size === 0) { setError("Choose an image up to 8 MB."); return; }
    setError(undefined);
    onChange(file);
  };

  return <div className="space-y-2" onDragOver={(event) => { event.preventDefault(); if (!disabled) setDragging(true); }}
    onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false); }}
    onDrop={(event) => { event.preventDefault(); setDragging(false); choose(event.dataTransfer.files[0]); }}>
    <div className="flex items-center gap-2"><p id={`${id}-label`} className="text-sm font-medium text-slate-700">{label}</p><span className="text-xs text-slate-400">Optional</span></div>
    <div className={cn("rounded-xl border border-slate-200 bg-slate-50/65 p-3 transition-colors sm:p-4", dragging && "border-blue-400 bg-blue-50", disabled && "opacity-60")}>
      <div className={cn("flex gap-4", isLogo ? "items-center" : "flex-col")}>
        {positioning && hasImage ? <ImagePositionEditor file={localFile} src={src} placement={positioning.value}
          onChange={positioning.onChange} aspect={positioning.aspect} disabled={disabled} /> : <div className={cn("relative flex shrink-0 items-center justify-center overflow-hidden border border-slate-200 bg-white", isLogo ? "h-20 w-20 rounded-full p-2" : "aspect-[4/1] w-full rounded-lg")}>
          {localFile ? <LocalImagePreview file={localFile} alt={`${label} preview`} className={imageClassName} /> : src ? <>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={src} alt={`${label} preview`} className={imageClassName} />
          </> : <ImagePlus className="h-6 w-6 text-slate-300" aria-hidden="true" />}
        </div>}
        <div className="min-w-0 flex-1 space-y-2">
          <p id={`${id}-hint`} className="text-xs leading-5 text-slate-500">{isLogo ? "A square image works best. Your logo will appear in a circle." : kind === "background" ? "The image stays fixed behind this group workspace, leaving the sidebar unchanged." : "The image appears behind the group heading and status text without blur or color effects."} JPG, PNG or WebP · up to 8 MB.</p>
          <input ref={inputRef} id={id} type="file" accept="image/jpeg,image/png,image/webp" className="sr-only" tabIndex={-1}
            aria-labelledby={`${id}-label`} aria-describedby={`${id}-hint`} disabled={disabled}
            onChange={(event) => { choose(event.target.files?.[0]); event.target.value = ""; }} />
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="secondary" size="sm" disabled={disabled} onClick={() => inputRef.current?.click()} aria-label={`Upload ${label.toLowerCase()}`}><Upload className="h-3.5 w-3.5" aria-hidden="true" />{hasImage ? "Replace image" : "Upload image"}</Button>
            {hasImage && <Button type="button" variant="ghost" size="sm" disabled={disabled} aria-label={`Remove ${label.toLowerCase()}`} onClick={() => { setError(undefined); onChange(currentUrl ? null : undefined); }}><X className="h-3.5 w-3.5" aria-hidden="true" />Remove</Button>}
            {value !== undefined && currentUrl && <button type="button" disabled={disabled} className="rounded px-1 py-2 text-xs font-medium text-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600" onClick={() => { setError(undefined); onChange(undefined); }}>Undo change</button>}
          </div>
          {value instanceof File && <p className="truncate text-xs text-slate-500" title={value.name}>{value.name}</p>}
        </div>
      </div>
    </div>
    {error && <p role="alert" className="text-xs text-red-700">{error}</p>}
  </div>;
}

function LocalImagePreview({ file, alt, className }: { file: File; alt: string; className: string }) {
  const imageRef = useRef<HTMLImageElement>(null);
  useEffect(() => {
    const url = URL.createObjectURL(file);
    if (imageRef.current) imageRef.current.src = url;
    return () => URL.revokeObjectURL(url);
  }, [file]);
  // A blob URL is scoped to this mounted preview and released on replacement.
  // eslint-disable-next-line @next/next/no-img-element
  return <img ref={imageRef} alt={alt} className={className} />;
}

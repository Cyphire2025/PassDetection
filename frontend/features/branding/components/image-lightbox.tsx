"use client";

import { useId, useRef } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { useModalKeyboardBoundary } from "@/components/ui/modal";

export function ImageLightbox({ src, name, onClose }: { src: string; name: string; onClose: () => void }) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const handleKeyDown = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: true, onClose });

  return createPortal(
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} onKeyDown={handleKeyDown}
      onClick={(event) => { event.stopPropagation(); if (event.target instanceof Node && !imageRef.current?.contains(event.target)) onClose(); }}
      className="fixed inset-0 z-[100] flex flex-col items-center justify-center gap-5 bg-slate-950/65 p-6 outline-none backdrop-blur-md sm:p-12">
      <h2 id={titleId} className="sr-only">{name} logo</h2>
      <button type="button" onClick={onClose} aria-label="Close logo preview" data-dialog-initial-focus
        className="absolute right-4 top-4 flex h-11 w-11 items-center justify-center rounded-full border border-white/25 bg-white/10 text-white transition-colors hover:bg-white/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white sm:right-6 sm:top-6">
        <X className="h-5 w-5" aria-hidden="true" />
      </button>
      {/* Authenticated, user-supplied images retain their aspect ratio without an optimizer proxy. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img ref={imageRef} src={src} alt={`${name} logo`} className="max-h-[70dvh] w-[min(32rem,80vw)] max-w-full rounded-2xl bg-white object-contain p-6 shadow-2xl sm:p-10" />
      <p className="text-center text-sm text-white/90">{name}<span className="mt-1 block text-xs text-white/65">Click outside the logo or press Esc to close</span></p>
    </div>, document.body,
  );
}

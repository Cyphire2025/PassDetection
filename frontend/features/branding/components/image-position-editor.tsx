"use client";

import { useEffect, useId, useRef } from "react";
import type { ImagePlacement } from "../image-crop";

export function ImagePositionEditor({ file, src, placement, onChange, disabled, aspect }: {
  file: File | null; src?: string | null; placement: ImagePlacement;
  onChange: (value: ImagePlacement) => void; disabled: boolean; aspect: number;
}) {
  const imageRef = useRef<HTMLImageElement>(null);
  const drag = useRef<{ x: number; y: number; placement: ImagePlacement } | null>(null);
  const id = useId();
  useEffect(() => {
    const url = file ? URL.createObjectURL(file) : src;
    if (imageRef.current && url) imageRef.current.src = url;
    return () => { if (file && url) URL.revokeObjectURL(url); };
  }, [file, src]);

  const change = (key: keyof ImagePlacement, value: number) => onChange({ ...placement, [key]: value });
  return <div className="space-y-3">
    <div role="img" aria-label="Image crop preview; use the position controls to adjust the visible area"
      className="relative mx-auto max-w-full touch-none overflow-hidden rounded-lg border border-slate-200 bg-slate-100"
      style={{ aspectRatio: aspect, width: `min(100%, ${aspect * 52}dvh)`, cursor: disabled ? "default" : "grab" }}
      onPointerDown={(event) => {
        if (disabled) return;
        event.preventDefault();
        event.currentTarget.setPointerCapture(event.pointerId);
        drag.current = { x: event.clientX, y: event.clientY, placement };
      }}
      onPointerMove={(event) => {
        if (!drag.current || disabled) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        const image = imageRef.current;
        if (!image?.naturalWidth || !bounds.width || !bounds.height) return;
        const scale = Math.max(bounds.width / image.naturalWidth, bounds.height / image.naturalHeight) * drag.current.placement.zoom;
        const overflowX = image.naturalWidth * scale - bounds.width;
        const overflowY = image.naturalHeight * scale - bounds.height;
        const { placement: start, x, y } = drag.current;
        onChange({ ...start,
          x: overflowX > 0.5 ? Math.max(0, Math.min(100, start.x - (event.clientX - x) / overflowX * 100)) : start.x,
          y: overflowY > 0.5 ? Math.max(0, Math.min(100, start.y - (event.clientY - y) / overflowY * 100)) : start.y,
        });
      }}
      onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img ref={imageRef} alt="" draggable={false} className="pointer-events-none h-full w-full object-cover"
        style={{ objectPosition: `${placement.x}% ${placement.y}%`, transform: `scale(${placement.zoom})`, transformOrigin: `${placement.x}% ${placement.y}%` }} />
    </div>
    <p className="text-xs text-slate-500">Drag the image inside the frame, or use the controls below. Only this area will be shown.</p>
    <div className="grid gap-3 sm:grid-cols-3">
      {([{ key: "x", label: "Horizontal position", min: 0, max: 100, step: 1 },
        { key: "y", label: "Vertical position", min: 0, max: 100, step: 1 },
        { key: "zoom", label: "Zoom", min: 1, max: 3, step: 0.05 }] as const).map(({ key, label, ...range }) => <label key={key} htmlFor={`${id}-${key}`} className="space-y-1 text-xs text-slate-600">
          <span>{label}</span><input id={`${id}-${key}`} type="range" {...range} value={placement[key]} disabled={disabled}
            onChange={(event) => change(key, Number(event.target.value))} className="block w-full accent-blue-600" />
        </label>)}
    </div>
  </div>;
}

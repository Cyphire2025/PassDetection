"use client";

import { useState } from "react";
import { Building2 } from "lucide-react";
import { cn } from "@/lib/utils/cn";
import { ImageLightbox } from "./image-lightbox";

export function CompanyLogo({ src, name, className }: { src?: string | null; name: string; className?: string }) {
  const [open, setOpen] = useState(false);
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const frame = cn("company-logo inline-flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-full border border-slate-200 bg-white shadow-sm", className);
  if (!src || failedSrc === src) return <span className={cn(frame, "bg-slate-50 text-slate-400")} aria-hidden="true"><Building2 className="h-[45%] w-[45%]" /></span>;
  return <>
    <button type="button" aria-label={`View ${name} logo`} onClick={(event) => { event.stopPropagation(); setOpen(true); }}
      className={cn(frame, "cursor-zoom-in p-1.5 transition-colors hover:border-blue-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2")}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt="" loading="lazy" decoding="async" onError={() => setFailedSrc(src)} className="h-full w-full object-contain" />
    </button>
    {open && <ImageLightbox src={src} name={name} onClose={() => setOpen(false)} />}
  </>;
}

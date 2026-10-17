"use client";

import { useState, type ReactNode } from "react";
import { cn } from "@/lib/utils/cn";

export function GroupBanner({ src, children }: { src?: string | null; children: ReactNode }) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const imageSrc = src && src !== failedSrc ? src : undefined;
  // Decoration changes must preserve open editors and the header's state.
  return <div role={imageSrc ? "region" : undefined} aria-label={imageSrc ? "Group header" : undefined}
    className={cn("flex flex-col gap-5", imageSrc && "group-banner relative isolate overflow-hidden rounded-2xl border border-slate-200/80 bg-slate-100 p-4 shadow-sm sm:p-5")}>
    {imageSrc && <>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={imageSrc} alt="" decoding="async" fetchPriority="high" onError={() => setFailedSrc(imageSrc)} className="pointer-events-none absolute inset-0 -z-20 h-full w-full object-cover" />
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 -z-10 bg-gradient-to-r from-white/40 via-white/20 to-white/15" />
    </>}
    {children}
  </div>;
}

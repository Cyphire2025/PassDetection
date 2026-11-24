"use client";

import { useMemo, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils/cn";
import { GroupBannerFrameContext } from "./group-banner-frame";

export function GroupBanner({ src, children }: { src?: string | null; children: ReactNode }) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const element = useRef<HTMLDivElement>(null);
  const [previewing, setPreviewing] = useState(false);
  const frame = useMemo(() => ({ element, previewing, setPreviewing }), [previewing]);
  const imageSrc = src && src !== failedSrc ? src : undefined;
  // Decoration changes must preserve open editors and the header's state.
  return (
    <GroupBannerFrameContext.Provider value={frame}>
      <div
        ref={element}
        data-group-banner-frame=""
        role={imageSrc ? "region" : undefined}
        aria-label={imageSrc ? "Group header" : undefined}
        className={cn(
          "flex flex-col gap-5",
          (imageSrc || previewing) && "group-banner relative isolate overflow-hidden rounded-2xl border border-slate-200/80 bg-slate-100 p-4 shadow-sm sm:p-5",
        )}
      >
        {imageSrc && <>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={imageSrc}
            alt=""
            decoding="async"
            fetchPriority="high"
            onError={() => setFailedSrc(imageSrc)}
            className="pointer-events-none absolute inset-0 -z-20 h-full w-full object-cover"
          />
        </>}
        {children}
      </div>
    </GroupBannerFrameContext.Provider>
  );
}

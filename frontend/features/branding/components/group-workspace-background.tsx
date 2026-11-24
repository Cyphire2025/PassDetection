"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

export function GroupWorkspaceBackground({ src, children }: { src?: string | null; children: ReactNode }) {
  const layer = useRef<HTMLDivElement>(null);
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const imageSrc = src && src !== failedSrc ? src : undefined;

  useEffect(() => {
    const element = layer.current;
    const main = element?.closest("main");
    if (!element || !main) return;
    const updateBounds = () => {
      const { left, top, width, height } = (main.parentElement ?? main).getBoundingClientRect();
      Object.assign(element.style, { left: `${left}px`, top: `${top}px`, width: `${width}px`, height: `${height}px` });
    };
    updateBounds();
    const observer = new ResizeObserver(updateBounds);
    observer.observe(main);
    window.addEventListener("resize", updateBounds);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", updateBounds);
    };
  }, [imageSrc]);

  return <div className="group-workspace relative isolate" data-group-background={imageSrc ? "" : undefined}>
    {imageSrc && <div ref={layer} aria-hidden="true" className="pointer-events-none fixed z-0 overflow-hidden">
      {/* Authenticated image bytes must bypass the public Next image optimizer. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={imageSrc} alt="" decoding="async" className="h-full w-full object-cover" onError={() => setFailedSrc(imageSrc)} />
    </div>}
    <div className="relative z-10 flex flex-col gap-5">{children}</div>
  </div>;
}

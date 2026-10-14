"use client";
import { useEffect, useRef } from "react";

export function SelectedDocumentPreview({ file, label }: { file: File; label: string }) {
  const preview = useRef<HTMLImageElement | HTMLIFrameElement | null>(null);
  useEffect(() => {
    const element = preview.current;
    if (!element) return;
    const url = URL.createObjectURL(file);
    element.src = url;
    return () => { element.removeAttribute("src"); URL.revokeObjectURL(url); };
  }, [file]);
  return <div className="flex aspect-[4/3] items-center justify-center rounded-xl bg-slate-50 p-3 sm:p-4">
    {file.type === "application/pdf" ? <iframe ref={(node) => { preview.current = node; }} title={label} className="h-full w-full border-0 bg-white" /> : (
      // Local selection is memory-only and is released on replacement or navigation.
      // eslint-disable-next-line @next/next/no-img-element
      <img ref={(node) => { preview.current = node; }} alt={label} className="h-full w-full object-contain" />
    )}
  </div>;
}

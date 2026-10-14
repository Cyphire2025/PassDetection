"use client";
import type { ReactNode } from "react";
import { LoaderCircle } from "lucide-react";

export function DocumentProcessingFrame({ children, status }: { children: ReactNode; status?: string }) {
  return <div className="relative overflow-hidden rounded-xl" aria-busy={Boolean(status)}>
    <div className={status ? "pointer-events-none select-none blur-sm" : undefined}>{children}</div>
    {status && <div role="status" aria-live="polite" className="absolute inset-0 flex min-h-32 flex-col items-center justify-center gap-3 bg-white/65 p-4 text-center text-sm font-medium text-blue-900 backdrop-blur-sm">
      <LoaderCircle aria-hidden="true" className="h-7 w-7 animate-spin motion-reduce:animate-none" />{status}
    </div>}
  </div>;
}

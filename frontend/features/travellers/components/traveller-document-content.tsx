"use client";
import { FileImage, RotateCw } from "lucide-react";
import type { useTravellerDocumentPreview } from "../hooks/use-traveller-document-preview";
export type TravellerDocumentProps = { id: string; label: string; draftId?: string; temporary?: boolean; available?: boolean };

export function TravellerDocumentContent({ label, temporary, available, frame, asset, error, retry, setError }: { label: string; temporary: boolean; available: boolean } & ReturnType<typeof useTravellerDocumentPreview>) {
  return <figure ref={frame} className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
    <figcaption
      className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3 text-sm font-medium text-slate-700"
    >
      <span className="flex items-center gap-2">
        <FileImage className="h-4 w-4 text-slate-400" />
        {label}
      </span>
      {temporary && <span className="text-xs text-blue-600">Updated draft</span>}
    </figcaption>
    <div className="flex aspect-[4/3] w-full items-center justify-center bg-slate-50 p-3 sm:p-4">
      {!available || error ? <div className="space-y-3 text-center text-sm text-slate-500">
        <p>
          {available ? "Preview could not be loaded." : "A readable copy is needed."}
        </p>
        {available && <button
          type="button"
          onClick={retry}
          className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 text-blue-700"
        >
          <RotateCw className="h-4 w-4" />Retry preview</button>}
      </div> : !asset ? <p role="status" className="text-sm text-slate-400">Loading protected document…</p> : asset.type === "application/pdf" ? <iframe title={label} src={asset.url} className="h-full w-full border-0 bg-white" /> : (
        // Only authenticated, bounded image blobs reach this local object URL.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={asset.url}
          alt={label}
          decoding="async"
          onError={() => setError(true)}
          className="h-full w-full rounded-lg object-contain"
        />
      )}
    </div>
  </figure>;
}

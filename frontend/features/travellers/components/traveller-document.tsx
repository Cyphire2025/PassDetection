"use client";

import { useEffect, useRef, useState } from "react";
import { FileImage, RotateCw } from "lucide-react";
import { returningApi } from "../api/returning.api";
import { returningDraftApi } from "../api/returning-draft.api";
import { queuedPrivatePreview } from "../services/private-preview-queue";

export function TravellerDocument({ id, label, draftId, temporary = false, available = true }: { id: string; label: string; draftId?: string; temporary?: boolean; available?: boolean }) {
  const frame = useRef<HTMLElement>(null);
  const [visible, setVisible] = useState(() => typeof IntersectionObserver === "undefined");
  const [asset, setAsset] = useState<{ url: string; type: string }>();
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!frame.current) return;
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) { setVisible(true); observer.disconnect(); }
    }, { rootMargin: "300px" });
    observer.observe(frame.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!visible || !available) return;
    const controller = new AbortController();
    let url: string | undefined;
    void queuedPrivatePreview(() => temporary && draftId ? returningDraftApi.document(id, draftId, controller.signal) : returningApi.document(id, controller.signal), controller.signal).then((blob) => {
      if (controller.signal.aborted) return;
      if (!blob.size || blob.size > 20 * 1024 * 1024 || !["image/jpeg", "image/png", "image/webp", "application/pdf"].includes(blob.type)) throw new Error("Unsupported preview");
      url = URL.createObjectURL(blob); setAsset({ url, type: blob.type });
    }).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => { controller.abort(); if (url) URL.revokeObjectURL(url); };
  }, [id, draftId, temporary, visible, available, attempt]);
  return <figure ref={frame} className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
    <figcaption className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3 text-sm font-medium text-slate-700"><span className="flex items-center gap-2"><FileImage className="h-4 w-4 text-slate-400" />{label}</span>{temporary && <span className="text-xs text-blue-600">Updated draft</span>}</figcaption>
    <div className="flex aspect-[4/3] w-full items-center justify-center bg-slate-50 p-3 sm:p-4">
      {!available || error ? <div className="space-y-3 text-center text-sm text-slate-500"><p>{available ? "Preview could not be loaded." : "A readable copy is needed."}</p>{available && <button type="button" onClick={() => { setError(false); setAsset(undefined); setAttempt((value) => value + 1); }} className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 text-blue-700"><RotateCw className="h-4 w-4" />Retry preview</button>}</div> : !asset ? <p role="status" className="text-sm text-slate-400">Loading protected document…</p> : asset.type === "application/pdf" ? <iframe title={label} src={asset.url} className="h-full w-full border-0 bg-white" /> : (
        // Only authenticated, bounded image blobs reach this local object URL.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={asset.url} alt={label} decoding="async" onError={() => setError(true)} className="h-full w-full rounded-lg object-contain" />
      )}
    </div>
  </figure>;
}

"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { returningApi } from "../api/returning.api";
import type { ReturningDocument } from "../types";

/** Exactly one authorised blob at a time; release it when the preview closes. */
export function ReturningDocumentPreview({ document, onViewed, onClose }: { document: ReturningDocument; onViewed: (id: string) => void; onClose: () => void }) {
  const [url, setUrl] = useState<string>();
  const [media, setMedia] = useState<string>();
  const [error, setError] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | undefined;
    void returningApi.document(document.id, controller.signal).then((blob) => {
      if (controller.signal.aborted) return;
      if (!blob.size || blob.size > 20 * 1024 * 1024 || !["image/jpeg", "image/png", "image/webp", "application/pdf"].includes(blob.type)) throw new Error("This document cannot be previewed here. Please upload a readable current copy.");
      objectUrl = URL.createObjectURL(blob);
      setUrl(objectUrl);
      setMedia(blob.type);
    }).catch((cause) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "This document is unavailable. Retry or upload a current copy.");
    });
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [document.id, attempt]);
  return <section aria-label={`${document.label} preview`} className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-medium text-slate-900">{document.label}</h3><Button type="button" size="sm" variant="secondary" onClick={onClose}>Close preview</Button></div>
    {error ? <div role="alert" className="space-y-2 text-sm text-red-700"><p>{error}</p><Button type="button" size="sm" variant="secondary" onClick={() => { setError(undefined); setUrl(undefined); setAttempt((value) => value + 1); }}>Retry preview</Button></div> : !url ? <div role="status" className="flex aspect-[3/4] items-center justify-center rounded-lg bg-slate-100 text-sm text-slate-500">Loading protected document…</div> : media === "application/pdf" ? <iframe title={document.label} src={url} className="h-[60dvh] min-h-64 w-full rounded-lg border-0 bg-white" onLoad={() => onViewed(document.id)} /> : (
      // Blob URLs have already passed the authorised document endpoint and MIME allowlist.
      // eslint-disable-next-line @next/next/no-img-element
      <img src={url} alt={document.label} loading="lazy" decoding="async" onLoad={() => onViewed(document.id)} onError={() => setError("This image could not be read. Retry or upload a current copy.")} className="max-h-[70dvh] w-full rounded-lg bg-white object-contain" />
    )}
  </section>;
}


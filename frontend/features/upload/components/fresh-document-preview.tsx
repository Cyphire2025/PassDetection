"use client";
import { useEffect, useRef, useState } from "react";
import type { freshDraftApi } from "../api/fresh-draft.api";
import { freshError } from "../services/fresh-draft-state";
import { queuedPrivatePreview } from "@/features/travellers/services/private-preview-queue";

export function FreshDocumentPreview({ id, label, api }: { id: string; label: string; api: Pick<ReturnType<typeof freshDraftApi>, "document"> }) {
  const element = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false), [url, setUrl] = useState<string>();
  const [error, setError] = useState<string>(), [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!element.current) return;
    const observer = new IntersectionObserver(([entry]) => { if (entry.isIntersecting) { setVisible(true); observer.disconnect(); } }, { rootMargin: "200px" });
    observer.observe(element.current); return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!visible) return;
    const controller = new AbortController(); let objectUrl: string | undefined;
    void queuedPrivatePreview(() => api.document(id, controller.signal), controller.signal).then((blob) => {
      if (controller.signal.aborted) return;
      if (!blob.size || blob.size > 20 * 1024 * 1024 || !["image/jpeg", "image/png", "image/webp"].includes(blob.type)) throw new Error("This preview is unavailable. Upload a readable image.");
      objectUrl = URL.createObjectURL(blob); setUrl(objectUrl);
    }).catch((cause) => { if (!controller.signal.aborted) setError(freshError(cause)); });
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [id, api, visible, attempt]);
  return <div ref={element} className="mt-3 overflow-hidden rounded-xl bg-slate-50">
    {error ? <div role="alert" className="p-3 text-sm text-red-700">{error}<button type="button" onClick={() => { setError(undefined); setAttempt((value) => value + 1); }} className="ml-2 min-h-11 font-semibold underline">Retry preview</button></div> : url ? (
      // Authorised bounded image blob; revoke on replacement or navigation.
      // eslint-disable-next-line @next/next/no-img-element
      <img src={url} alt={label} loading="lazy" decoding="async" onError={() => setError("This image could not be displayed. Retry or upload a readable copy.")} className="max-h-[55dvh] w-full object-contain" />
    ) : <div role="status" className="flex min-h-40 items-center justify-center text-sm text-slate-500">Loading document…</div>}
  </div>;
}

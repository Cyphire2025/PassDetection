"use client";

import { Loader2, Pencil } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  acquireDocumentThumbnailSlot,
  documentThumbnailUrl,
} from "../services/document-thumbnail-scheduler";

export function DocumentCell({
  label,
  url,
  file,
  filename,
  revision = 0,
  canEdit = false,
  onEdit,
}: {
  label: string;
  url?: string | null;
  file?: File;
  filename?: string | null;
  revision?: number;
  canEdit?: boolean;
  onEdit?: (trigger: HTMLButtonElement) => void;
}) {
  const effectiveUrl = url ? appendCacheRevision(url, revision) : null;
  return (
    <td className="px-5 py-4">
      {effectiveUrl || file ? (
        <div className="space-y-2">
          {file ? (
            <LocalDocumentThumbnail file={file} label={label} />
          ) : effectiveUrl ? (
            <a
              href={effectiveUrl}
              target="_blank"
              rel="noreferrer"
              aria-label={`Open ${label} in a new tab`}
              className="block rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            >
              <DeferredDocumentThumbnail key={effectiveUrl} url={effectiveUrl} label={label} />
            </a>
          ) : null}
          <div className="flex max-w-44 items-center justify-between gap-2">
            <div className="min-w-0 truncate text-xs text-slate-500">{filename ?? "Saved document"}</div>
            {!file && effectiveUrl && canEdit && onEdit && (
              <button
                type="button"
                onClick={(event) => onEdit(event.currentTarget)}
                className="inline-flex shrink-0 items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              >
                <Pencil className="h-3.5 w-3.5" /> Edit
              </button>
            )}
          </div>
        </div>
      ) : (
        <div className="flex h-24 w-36 items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50 text-xs font-medium text-slate-400">
          No document
        </div>
      )}
    </td>
  );
}

export function DeferredDocumentThumbnail({ url, label }: { url: string; label: string }) {
  const frameRef = useRef<HTMLDivElement | null>(null);
  const releaseSlotRef = useRef<(() => void) | null>(null);
  const retryTimerRef = useRef<number | null>(null);
  const [shouldLoad, setShouldLoad] = useState(false);
  const [loadUrl, setLoadUrl] = useState<string | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [failed, setFailed] = useState(false);
  const thumbnailUrl = documentThumbnailUrl(url);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    if (typeof IntersectionObserver === "undefined") {
      const timer = globalThis.setTimeout(() => setShouldLoad(true), 0);
      return () => globalThis.clearTimeout(timer);
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        setShouldLoad(true);
        observer.disconnect();
      },
      { rootMargin: "200px 0px" },
    );
    observer.observe(frame);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!shouldLoad || failed) return;
    const controller = new AbortController();
    let disposed = false;

    void acquireDocumentThumbnailSlot(controller.signal)
      .then((release) => {
        if (disposed) {
          release();
          return;
        }
        releaseSlotRef.current = release;
        setLoadUrl(thumbnailUrl);
      })
      .catch((error: unknown) => {
        if (
          !disposed
          && (!(error instanceof Error) || error.name !== "AbortError")
        ) {
          setFailed(true);
        }
      });

    return () => {
      disposed = true;
      controller.abort();
      releaseSlotRef.current?.();
      releaseSlotRef.current = null;
      if (retryTimerRef.current !== null) {
        window.clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
    };
  }, [failed, loadAttempt, shouldLoad, thumbnailUrl]);

  const releaseSlot = () => {
    releaseSlotRef.current?.();
    releaseSlotRef.current = null;
  };

  const handleLoadError = () => {
    releaseSlot();
    setLoadUrl(null);
    if (loadAttempt === 0) {
      retryTimerRef.current = window.setTimeout(() => {
        retryTimerRef.current = null;
        setLoadAttempt(1);
      }, 1_000);
      return;
    }
    setFailed(true);
  };

  return (
    <div
      ref={frameRef}
      className="flex h-24 w-36 items-center justify-center rounded-lg border border-slate-200 bg-slate-50"
      aria-live="polite"
    >
      {loadUrl ? (
        <>
          {/* Keep this browser-side so the HttpOnly authentication cookie is attached. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={loadUrl}
            alt={label}
            loading="eager"
            decoding="async"
            fetchPriority="low"
            onLoad={releaseSlot}
            onError={handleLoadError}
            className="h-full w-full rounded-lg object-contain"
          />
        </>
      ) : failed ? (
        <span className="px-2 text-center text-xs text-slate-400">
          Preview unavailable
        </span>
      ) : shouldLoad ? (
        <Loader2 className="h-4 w-4 animate-spin text-slate-400" aria-label="Loading preview" />
      ) : (
        <span className="text-xs text-slate-400" aria-hidden="true">Preview</span>
      )}
    </div>
  );
}

function appendCacheRevision(url: string, revision: number) {
  if (revision === 0) return url;
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}ui_edit_revision=${revision}`;
}

export function LocalDocumentThumbnail({ file, label }: { file: File; label: string }) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  useEffect(() => {
    const nextUrl = URL.createObjectURL(file);
    const timer = window.setTimeout(() => setObjectUrl(nextUrl), 0);
    return () => {
      window.clearTimeout(timer);
      URL.revokeObjectURL(nextUrl);
    };
  }, [file]);
  if (!objectUrl) {
    return (
      <div
        className="flex h-24 w-36 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-xs text-slate-400"
        role="status"
      >
        Loading preview
      </div>
    );
  }
  return (
    <a
      href={objectUrl}
      target="_blank"
      rel="noreferrer"
      aria-label={`Open ${label} preview in a new tab`}
      className="block rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
    >
      {/* Document imports accept image files; the object URL is revoked on replacement/unmount. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={objectUrl}
        alt={label}
        loading="lazy"
        decoding="async"
        className="h-24 w-36 rounded-lg border border-slate-200 bg-slate-50 object-contain"
      />
    </a>
  );
}

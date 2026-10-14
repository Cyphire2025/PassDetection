"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { queuedPrivatePreview } from "@/features/travellers/services/private-preview-queue";
import { uploadApi } from "../api/upload.api";

interface ProtectedUploadDocumentImageProps {
  token: string;
  submissionId: string;
  uploadSessionId: string;
  documentType: "front" | "back" | "photo" | "cover" | "back_cover";
  alt: string;
  className?: string;
  overlay?: ReactNode;
}

export function ProtectedUploadDocumentImage({
  token,
  submissionId,
  uploadSessionId,
  documentType,
  alt,
  className,
  overlay,
}: ProtectedUploadDocumentImageProps) {
  const frame = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(() => typeof IntersectionObserver === "undefined");
  useEffect(() => {
    if (!frame.current) return;
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => { if (entry.isIntersecting) { setVisible(true); observer.disconnect(); } }, { rootMargin: "300px" });
    observer.observe(frame.current);
    return () => observer.disconnect();
  }, []);
  const [loadedPreview, setLoadedPreview] = useState<{
    requestKey: string;
    objectUrl: string;
  } | null>(null);
  const [failedRequestKey, setFailedRequestKey] = useState<string | null>(null);
  const [retryVersion, setRetryVersion] = useState(0);
  const [orientation, setOrientation] = useState<"portrait" | "landscape">("landscape");
  const requestKey = JSON.stringify([
    token,
    submissionId,
    uploadSessionId,
    documentType,
    retryVersion,
  ]);

  useEffect(() => {
    if (!visible) return;
    const controller = new AbortController();
    let activeObjectUrl: string | null = null;

    void queuedPrivatePreview(() => uploadApi.getUploadDocument(
      token,
      submissionId,
      documentType,
      uploadSessionId,
      controller.signal,
    ), controller.signal).then((blob) => {
      if (controller.signal.aborted) return;
      if (!blob.size || blob.size > 20 * 1024 * 1024 || !["image/jpeg", "image/png", "image/webp"].includes(blob.type)) throw new Error("Unsupported preview");
      activeObjectUrl = URL.createObjectURL(blob);
      setLoadedPreview({
        requestKey,
        objectUrl: activeObjectUrl,
      });
      setFailedRequestKey(null);
    }).catch(() => {
      if (!controller.signal.aborted) {
        setFailedRequestKey(requestKey);
      }
    });

    return () => {
      controller.abort();
      if (activeObjectUrl) URL.revokeObjectURL(activeObjectUrl);
    };
  }, [
    documentType,
    requestKey,
    submissionId,
    token,
    uploadSessionId,
    visible,
  ]);

  if (failedRequestKey === requestKey) {
    return (
      <div
        ref={frame}
        role="alert"
        className="flex aspect-[4/3] w-full flex-col items-center justify-center gap-3 bg-red-50 px-4 text-center text-sm text-red-700"
      >
        <span>Secure preview is unavailable.</span>
        <button
          type="button"
          className="rounded-md border border-red-300 bg-white px-3 py-1.5 font-medium text-red-700 hover:bg-red-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500"
          onClick={() => setRetryVersion((version) => version + 1)}
        >
          Retry preview
        </button>
      </div>
    );
  }

  if (!loadedPreview || loadedPreview.requestKey !== requestKey) {
    return (
      <div
        ref={frame}
        role="status"
        aria-live="polite"
        aria-label={`${alt} preview loading`}
        className="flex aspect-[4/3] w-full items-center justify-center bg-slate-50 text-sm text-slate-400"
      >
        Loading secure preview
      </div>
    );
  }

  // The preview has a fixed size, while the inner wrapper follows the displayed
  // image. Field overlays then remain aligned when the image is letterboxed.
  // Object URLs are created from authenticated same-origin API responses.
  return (
    <div
      ref={frame}
      data-testid="secure-document-preview-frame"
      data-orientation={orientation}
      className={`flex aspect-[4/3] w-full items-center justify-center bg-slate-50 p-3 sm:p-4 ${className ?? ""}`}
    >
      <div className="relative inline-block max-w-full leading-none">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={loadedPreview.objectUrl}
          alt={alt}
          onLoad={(event) => setOrientation(event.currentTarget.naturalHeight > event.currentTarget.naturalWidth ? "portrait" : "landscape")}
          onError={() => setFailedRequestKey(requestKey)}
          style={{ maxHeight: "min(320px, 55vw)", maxWidth: "100%", width: "auto", height: "auto", objectFit: "contain" }}
          className="block"
        />
        {overlay}
      </div>
    </div>
  );
}

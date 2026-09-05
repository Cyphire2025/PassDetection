"use client";

import { useEffect, useState, type ReactNode } from "react";
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
    const controller = new AbortController();
    let activeObjectUrl: string | null = null;

    void uploadApi.getUploadDocument(
      token,
      submissionId,
      documentType,
      uploadSessionId,
      controller.signal,
    ).then((blob) => {
      if (controller.signal.aborted) return;
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
  ]);

  if (failedRequestKey === requestKey) {
    return (
      <div
        role="alert"
        className="flex min-h-48 flex-col items-center justify-center gap-3 bg-red-50 px-4 text-center text-sm text-red-700"
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
        role="status"
        aria-live="polite"
        aria-label={`${alt} preview loading`}
        className="flex min-h-48 items-center justify-center bg-slate-50 text-sm text-slate-400"
      >
        Loading secure preview
      </div>
    );
  }

  // The frame has a fixed size, while the inner wrapper follows the displayed
  // image. Field overlays then remain aligned when the image is letterboxed.
  // Object URLs are created from authenticated same-origin API responses.
  return (
    <div
      data-testid="secure-document-preview-frame"
      data-orientation={orientation}
      style={{ width: orientation === "portrait" ? 220 : 360, height: orientation === "portrait" ? 300 : 230, maxWidth: "100%", marginInline: "auto" }}
      className={`flex items-center justify-center rounded-lg bg-slate-50 ${className ?? ""}`}
    >
      <div className="relative inline-block max-w-full leading-none">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={loadedPreview.objectUrl}
          alt={alt}
          onLoad={(event) => setOrientation(event.currentTarget.naturalHeight > event.currentTarget.naturalWidth ? "portrait" : "landscape")}
          onError={() => setFailedRequestKey(requestKey)}
          style={{ maxHeight: orientation === "portrait" ? 300 : 230, maxWidth: "100%", width: "auto", height: "auto", objectFit: "contain" }}
          className="block rounded-lg"
        />
        {overlay}
      </div>
    </div>
  );
}

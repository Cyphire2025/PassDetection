"use client";

import { useEffect, useRef, useState } from "react";
import { companyPeopleApi } from "../api/company-people.api";
import type { CompanyDocumentAsset } from "../types/company-people";
import { queuedPrivatePreview } from "@/features/travellers/services/private-preview-queue";

const TYPES = ["image/jpeg", "image/png", "image/webp", "application/pdf"];
export type PreviewDocument = { kind: "version"; asset: CompanyDocumentAsset } | { kind: "source"; sourceId: string; side: string };
export function useCompanyDocumentPreview(agencyId: string, companyId: string, personId: string, document: PreviewDocument) {
  const frame = useRef<HTMLElement>(null);
  const [visible, setVisible] = useState(() => typeof IntersectionObserver === "undefined");
  const [attempt, setAttempt] = useState(0);
  const [preview, setPreview] = useState<{ url: string; type: string }>();
  const [error, setError] = useState(false);
  const asset = document.kind === "version" ? document.asset : undefined;
  const sourceId = document.kind === "source" ? document.sourceId : undefined;
  const side = document.kind === "source" ? document.side : document.asset.side;
  const assetId = asset?.id;
  const supported = !asset || asset.availability === "available" && asset.byte_size > 0 && asset.byte_size <= 20 * 1024 * 1024 && TYPES.includes(asset.content_type);
  useEffect(() => {
    if (!frame.current || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => { if (entry.isIntersecting) { setVisible(true); observer.disconnect(); } }, { rootMargin: "200px" });
    observer.observe(frame.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!supported || !visible) return;
    const controller = new AbortController(); let objectUrl: string | undefined;
    void queuedPrivatePreview(() => sourceId ? companyPeopleApi.sourceAsset(agencyId, companyId, personId, sourceId, side, controller.signal) : companyPeopleApi.asset(agencyId, companyId, personId, assetId!, controller.signal), controller.signal).then((blob) => {
      if (controller.signal.aborted) return;
      if (!blob.size || blob.size > 20 * 1024 * 1024 || !TYPES.includes(blob.type)) throw new Error("Unsupported preview");
      objectUrl = URL.createObjectURL(blob); setPreview({ url: objectUrl, type: blob.type });
    }).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [agencyId, companyId, personId, assetId, sourceId, side, supported, visible, attempt]);
  const retry = () => { setError(false); setPreview(undefined); setAttempt((value) => value + 1); };
  return { frame, preview, error: error || !supported, retry: supported ? retry : undefined, label: `${side.replaceAll("_", " ")} document`, onImageError: () => setError(true) };
}

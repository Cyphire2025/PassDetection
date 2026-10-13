"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { companyPeopleApi } from "../api/company-people.api";
import type { CompanyDocumentAsset } from "../types/company-people";
import { CompanyError } from "./company-feedback";

const PREVIEW_TYPES = ["image/jpeg", "image/png", "image/webp", "application/pdf"];

export function CompanyDocumentPreview({ agencyId, companyId, personId, document, onClose }: { agencyId: string; companyId: string; personId: string; document: { kind: "version"; asset: CompanyDocumentAsset } | { kind: "source"; sourceId: string; side: string }; onClose: () => void }) {
  const [url, setUrl] = useState<string>();
  const [type, setType] = useState<string>();
  const [error, setError] = useState(false);
  const asset = document.kind === "version" ? document.asset : undefined;
  const sourceId = document.kind === "source" ? document.sourceId : undefined;
  const side = document.kind === "source" ? document.side : document.asset.side;
  const assetId = asset?.id;
  const supported = !asset || asset.byte_size > 0 && asset.byte_size <= 20 * 1024 * 1024 && PREVIEW_TYPES.includes(asset.content_type);
  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | undefined;
    if (!supported) return;
    const request = sourceId ? companyPeopleApi.sourceAsset(agencyId, companyId, personId, sourceId, side, controller.signal) : companyPeopleApi.asset(agencyId, companyId, personId, assetId!, controller.signal);
    void request.then((blob) => {
      if (controller.signal.aborted) return;
      if (!blob.size || blob.size > 20 * 1024 * 1024 || !PREVIEW_TYPES.includes(blob.type)) throw new Error("Unsupported preview");
      objectUrl = URL.createObjectURL(blob); setUrl(objectUrl); setType(blob.type);
    }).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [agencyId, companyId, personId, assetId, sourceId, side, supported]);
  const label = `${side.replaceAll("_", " ")} document`;
  return <section aria-label="Document preview" className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-3"><div className="flex items-center justify-between gap-2"><h3 className="text-sm font-medium text-slate-900">{label}</h3><Button type="button" variant="ghost" size="sm" onClick={onClose}>Close preview</Button></div>{error || !supported ? <CompanyError message="This file could not be previewed. Close it and try again." /> : !url ? <p role="status" className="py-8 text-center text-sm text-slate-500">Loading document…</p> : type === "application/pdf" ? <iframe title={label} src={url} className="h-[60dvh] w-full rounded border-0 bg-white" /> : (
    // Protected, MIME-checked local blob URLs do not use the public image optimiser.
    // eslint-disable-next-line @next/next/no-img-element
    <img src={url} alt={label} loading="lazy" decoding="async" className="max-h-[65dvh] w-full rounded object-contain" onError={() => setError(true)} />
  )}</section>;
}

"use client";

import { Button } from "@/components/ui/button";
import { useCompanyDocumentPreview, type PreviewDocument } from "../hooks/use-company-document-preview";
import { CompanyError } from "./company-feedback";

export function CompanyDocumentPreview({ agencyId, companyId, personId, document, onClose }: { agencyId: string; companyId: string; personId: string; document: PreviewDocument; onClose?: () => void }) {
  const { frame, preview, error, retry, label, onImageError } = useCompanyDocumentPreview(agencyId, companyId, personId, document);
  return <section ref={frame} aria-label="Document preview" className="overflow-hidden rounded-xl border border-slate-200 bg-slate-50">
    <div className="flex items-center justify-between gap-2 border-b border-slate-100 bg-white px-4 py-3"><h3 className="text-sm font-medium capitalize text-slate-700">{label}</h3>{onClose && <Button type="button" variant="ghost" size="sm" onClick={onClose}>Close preview</Button>}</div>
    <div className="flex aspect-[4/3] items-center justify-center p-3">{error ? <CompanyError message="This file could not be previewed." retry={retry} /> : !preview ? <p role="status" className="py-8 text-center text-sm text-slate-500">Loading document…</p> : preview.type === "application/pdf" ? <iframe title={label} src={preview.url} className="h-full w-full rounded border-0 bg-white" /> : (
      // Protected, MIME-checked local blob URLs do not use the public image optimiser.
      // eslint-disable-next-line @next/next/no-img-element
      <img src={preview.url} alt={label} loading="lazy" decoding="async" className="h-full w-full rounded object-contain" onError={onImageError} />
    )}</div>
  </section>;
}

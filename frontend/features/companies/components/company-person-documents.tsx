"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { companyPeopleApi } from "../api/company-people.api";
import { useCompanyQueryContext } from "../hooks/use-companies";
import type { CompanyDocumentAsset, CompanyPersonRecord } from "../types/company-people";
import { CompanyError, CompanyLoading, CompanyPagination } from "./company-feedback";
import { CompanyDocumentUploadForm } from "./company-document-upload";
import { toLabel } from "@/features/upload/services/upload-flow-helpers";

import { CompanyDocumentPreview } from "./company-document-preview";
import { CompanyOriginalDocuments } from "./company-original-documents";

export function CompanyPersonDocuments({ agencyId, companyId, record, onBusy, onSaved }: { agencyId: string; companyId: string; record: CompanyPersonRecord; onBusy: (busy: boolean) => void; onSaved: () => Promise<void> }) {
  const personId = record.id;
  const { scope, ready } = useCompanyQueryContext(agencyId);
  const [cursor, setCursor] = useState<string>();
  const [preview, setPreview] = useState<CompanyDocumentAsset>();
  const [upload, setUpload] = useState(false);
  const canUpload = record.status === "active";
  const documents = useQuery({ queryKey: [...scope, companyId, "people", personId, "documents", cursor], queryFn: ({ signal }) => companyPeopleApi.documents(agencyId, companyId, personId, cursor, signal), enabled: ready, staleTime: 0, gcTime: 0, refetchOnWindowFocus: false, retry: false });
  return <div className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-xs text-slate-500">Previous versions are kept.</p>{(!upload || !canUpload) && <Button type="button" variant="secondary" className="min-h-11" disabled={!ready || documents.isError || !canUpload} onClick={() => { setPreview(undefined); setUpload(true); }}>Add document version</Button>}</div>
    {!canUpload && <p role="status" className="text-sm text-slate-600">This identity needs review before adding documents.</p>}
    {ready && !documents.isError && canUpload && upload && <CompanyDocumentUploadForm agencyId={agencyId} companyId={companyId} record={record} onBusy={onBusy} onCancel={() => setUpload(false)} onSaved={async () => { await onSaved(); setUpload(false); setCursor(undefined); }} />}
    {!ready || documents.isLoading ? <CompanyLoading /> : documents.isError ? <CompanyError message="Documents could not be loaded." retry={() => void documents.refetch()} /> : <>
      <ul className="space-y-3">{documents.data?.items.map((version) => <li key={version.id} className="rounded-xl border border-slate-200 p-3"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold text-slate-900">Version {version.revision_number}{version.is_current ? " · Current" : ""}</h3><p className="text-xs text-slate-500">{new Date(version.created_at).toLocaleDateString()}</p></div><div className="mt-3 flex flex-wrap gap-2">{version.assets.map((asset) => <Button key={asset.id} type="button" variant="secondary" size="sm" className="min-h-11" disabled={asset.availability !== "available"} aria-label={`View ${asset.side.replaceAll("_", " ")} from version ${version.revision_number}`} onClick={() => setPreview(asset)}>{asset.side.replaceAll("_", " ")}{asset.availability !== "available" ? " · Unavailable" : ""}</Button>)}</div>{!version.assets.length && <p className="mt-2 text-xs text-slate-500">No images in this version.</p>}<details className="mt-3 text-xs text-slate-600"><summary className="w-fit cursor-pointer rounded font-medium focus-visible:ring-2 focus-visible:ring-blue-600">Version details</summary><dl className="mt-3 grid gap-3 sm:grid-cols-2">{Object.entries(version.fields).map(([key, value]) => <div key={key} className="min-w-0"><dt className="text-slate-500">{toLabel(key)}</dt><dd className="mt-0.5 break-words text-slate-800">{value || "—"}</dd></div>)}</dl></details></li>)}</ul>
      {!documents.data?.items.length && <p className="text-sm text-slate-500">No saved document versions.</p>}
      {(cursor || documents.data?.has_more) && <CompanyPagination cursor={cursor} hasMore={documents.data?.has_more ?? false} nextCursor={documents.data?.next_cursor ?? null} pending={documents.isFetching} onChange={(value) => { setCursor(value); setPreview(undefined); }} />}
      {preview && <CompanyDocumentPreview key={preview.id} agencyId={agencyId} companyId={companyId} personId={personId} document={{ kind: "version", asset: preview }} onClose={() => setPreview(undefined)} />}
      <CompanyOriginalDocuments agencyId={agencyId} companyId={companyId} personId={personId} />
    </>}
  </div>;
}

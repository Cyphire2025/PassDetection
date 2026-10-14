"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { getPassportCountryOptions } from "@/lib/utils/passport-country";
import { cleanPassportReviewFields } from "@/features/passports/utils/passport-review";
import { companyPeopleApi } from "../api/company-people.api";
import type { CompanyDocumentUpload, CompanyPersonRecord } from "../types/company-people";
import { CompanyError, companyErrorMessage } from "./company-feedback";
import { CompanyPassportFields } from "./company-passport-fields";

const COUNTRIES = getPassportCountryOptions(3);
const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];
function countriesForRecord(record: CompanyPersonRecord) {
  return record.current_document?.issuing_country === "UNK"
    ? [{ value: "UNK", label: "Not recorded" }, ...COUNTRIES] : COUNTRIES;
}

export function CompanyDocumentUploadForm({ agencyId, companyId, record, onSaved, onCancel, onBusy }: { agencyId: string; companyId: string; record: CompanyPersonRecord; onSaved: () => Promise<void>; onCancel: () => void; onBusy: (busy: boolean) => void }) {
  const [opened] = useState(record);
  const [kind, setKind] = useState<CompanyDocumentUpload["change_kind"]>(record.current_document ? "scan" : "renewal");
  const [side, setSide] = useState<CompanyDocumentUpload["side"]>("front");
  const [issuer, setIssuer] = useState(record.current_document?.issuing_country ?? "");
  const [documentType, setDocumentType] = useState(record.current_document?.document_type ?? "P");
  const [fields, setFields] = useState<Record<string, string>>(() => ({ ...record.current_document?.fields }));
  const [file, setFile] = useState<File>();
  const [preview, setPreview] = useState<string>();
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();
  const requestKey = useRef<string | null>(null);
  const inFlight = useRef(false);
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);
  const changed = () => { requestKey.current = null; setConfirmed(false); setError(undefined); };
  return <form className="space-y-4 rounded-xl border border-blue-100 bg-blue-50/30 p-3 sm:p-4" onSubmit={async (event) => {
    event.preventDefault();
    if (record.status !== "active" || !file || !confirmed || inFlight.current || !issuer || !fields.passport_number?.trim()) return;
    inFlight.current = true; setPending(true); onBusy(true); setError(undefined); requestKey.current ??= crypto.randomUUID();
    try {
      await companyPeopleApi.upload(agencyId, companyId, opened.id, { expected_revision: opened.revision, idempotency_key: requestKey.current, reason: reason.trim(), change_kind: kind, side: kind === "renewal" ? "front" : side, issuing_country: issuer, document_type: documentType, fields: cleanPassportReviewFields(fields) }, file);
      await onSaved();
    } catch (cause) { setError(companyErrorMessage(cause, "The document could not be saved. Reopen the record if it has changed.")); }
    finally { inFlight.current = false; setPending(false); onBusy(false); }
  }}>
    <div><h3 className="text-sm font-semibold text-slate-950">Add document version</h3><p className="mt-1 text-xs leading-5 text-slate-500">The new image becomes current. Previous versions and trip records are kept.</p></div>
    <fieldset disabled={pending} className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2"><label className="block space-y-1.5 text-sm font-medium text-slate-700">Update type<select value={kind} onChange={(event) => { changed(); setKind(event.target.value as CompanyDocumentUpload["change_kind"]); }} className="min-h-11 w-full rounded-lg border border-slate-300 bg-white px-3"><option value="scan" disabled={!opened.current_document}>Better scan</option><option value="renewal">{opened.current_document ? "Renewed passport" : "New passport"}</option><option value="correction" disabled={!opened.current_document}>Correction</option></select></label><label className="block space-y-1.5 text-sm font-medium text-slate-700">Document image<select value={kind === "renewal" ? "front" : side} disabled={kind === "renewal"} onChange={(event) => { changed(); setSide(event.target.value as CompanyDocumentUpload["side"]); }} className="min-h-11 w-full rounded-lg border border-slate-300 bg-white px-3"><option value="front">Passport front</option><option value="back">Passport back</option><option value="cover">Front cover</option><option value="back_cover">Back cover</option><option value="photo">Photo</option></select></label></div>
      <label className="block space-y-2 text-sm font-medium text-slate-700">New image<input type="file" accept="image/jpeg,image/png,image/webp" required className="block w-full min-w-0 rounded-lg border border-slate-300 bg-white p-2 text-xs file:mr-3 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-2 file:text-sm" onChange={(event) => {
        changed(); const next = event.target.files?.[0];
        if (!next || !IMAGE_TYPES.includes(next.type) || !next.size || next.size > 20 * 1024 * 1024) { setFile(undefined); setPreview(undefined); if (next) setError("Choose a JPEG, PNG or WebP image up to 20 MB."); return; }
        setFile(next); setPreview(URL.createObjectURL(next));
      }} /><span className="block text-xs font-normal text-slate-500">JPEG, PNG or WebP · up to 20 MB</span></label>
      {preview && (
        // This preview is the operator's locally selected, size-checked image.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={preview} alt="New document image" className="max-h-72 w-full rounded-lg bg-white object-contain" onError={() => { setFile(undefined); setError("This image could not be read. Choose another file."); }} />
      )}
      <div className="grid gap-3 sm:grid-cols-2"><label className="block space-y-1.5 text-sm font-medium text-slate-700">Issuing country<select required value={issuer} onChange={(event) => { changed(); setIssuer(event.target.value); }} className="min-h-11 w-full rounded-lg border border-slate-300 bg-white px-3"><option value="">Select country</option>{countriesForRecord(opened).map((country) => <option key={country.value} value={country.value}>{country.label}</option>)}</select></label><Input label="Document type" required maxLength={16} value={documentType} onChange={(event) => { changed(); setDocumentType(event.target.value); }} /></div>
      <CompanyPassportFields fields={fields} onChange={(key, value) => { changed(); setFields((current) => ({ ...current, [key]: value })); }} />
      <Input label="Reason for document update" required minLength={3} maxLength={500} value={reason} onChange={(event) => { changed(); setReason(event.target.value); }} />
      <label className="flex items-start gap-3 text-sm leading-6 text-slate-700"><input type="checkbox" className="mt-1" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} required />I checked this image and the passport details for this person.</label>
    </fieldset>
    {error && <CompanyError message={error} />}
    <div className="flex flex-wrap justify-end gap-2"><Button type="button" variant="secondary" disabled={pending} onClick={onCancel}>Cancel</Button><Button type="submit" disabled={!file || !confirmed || !issuer || !documentType.trim() || !fields.passport_number?.trim() || reason.trim().length < 3} isLoading={pending}>Save document version</Button></div>
  </form>;
}

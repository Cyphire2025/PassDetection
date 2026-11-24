"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { cleanPassportReviewFields } from "@/features/passports/utils/passport-review";
import { companyPeopleApi } from "../api/company-people.api";
import type { CompanyDocumentUpload, CompanyPersonRecord } from "../types/company-people";
import { companyErrorMessage } from "../utils/company-errors";

const IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const MAX_IMAGE_BYTES = 20 * 1024 * 1024;

interface DocumentDraft {
  kind: CompanyDocumentUpload["change_kind"];
  side: CompanyDocumentUpload["side"];
  issuer: string;
  documentType: string;
  fields: Record<string, string>;
  reason: string;
}

export interface CompanyDocumentUploadProps {
  agencyId: string;
  companyId: string;
  record: CompanyPersonRecord;
  onSaved: () => Promise<void>;
  onCancel: () => void;
  onBusy: (busy: boolean) => void;
}

/** Keep edits and retries bound to the record revision opened by the operator. */
export function useCompanyDocumentUpload({ agencyId, companyId, record, onSaved, onBusy }: CompanyDocumentUploadProps) {
  const [opened] = useState(record);
  const [draft, setDraft] = useState<DocumentDraft>(() => ({
    kind: record.current_document ? "scan" : "renewal",
    side: "front",
    issuer: record.current_document?.issuing_country ?? "",
    documentType: record.current_document?.document_type ?? "P",
    fields: { ...record.current_document?.fields },
    reason: "",
  }));
  const [file, setFile] = useState<File>();
  const [preview, setPreview] = useState<string>();
  const [confirmed, setConfirmed] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();
  const requestKey = useRef<string | null>(null);
  const inFlight = useRef(false);

  useEffect(() => () => {
    if (preview) URL.revokeObjectURL(preview);
  }, [preview]);

  function changed() {
    requestKey.current = null;
    setConfirmed(false);
    setError(undefined);
  }

  function change<K extends keyof DocumentDraft>(key: K, value: DocumentDraft[K]) {
    changed();
    setDraft((current) => ({ ...current, [key]: value }));
  }

  function selectFile(next: File | undefined) {
    changed();
    if (!next || !IMAGE_TYPES.has(next.type) || !next.size || next.size > MAX_IMAGE_BYTES) {
      setFile(undefined);
      setPreview(undefined);
      if (next) setError("Choose a JPEG, PNG or WebP image up to 20 MB.");
      return;
    }
    setFile(next);
    setPreview(URL.createObjectURL(next));
  }

  function changeField(key: string, value: string) {
    changed();
    setDraft((current) => ({ ...current, fields: { ...current.fields, [key]: value } }));
  }

  function imageFailed() {
    setFile(undefined);
    setError("This image could not be read. Choose another file.");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (record.status !== "active" || !file || !confirmed || inFlight.current
      || !draft.issuer || !draft.fields.passport_number?.trim()) return;
    inFlight.current = true;
    setPending(true);
    onBusy(true);
    setError(undefined);
    requestKey.current ??= crypto.randomUUID();
    try {
      await companyPeopleApi.upload(agencyId, companyId, opened.id, {
        expected_revision: opened.revision,
        idempotency_key: requestKey.current,
        reason: draft.reason.trim(),
        change_kind: draft.kind,
        side: draft.kind === "renewal" ? "front" : draft.side,
        issuing_country: draft.issuer,
        document_type: draft.documentType,
        fields: cleanPassportReviewFields(draft.fields),
      }, file);
      await onSaved();
    } catch (cause) {
      setError(companyErrorMessage(cause, "The document could not be saved. Reopen the record if it has changed."));
    } finally {
      inFlight.current = false;
      setPending(false);
      onBusy(false);
    }
  }

  const canSave = Boolean(file && confirmed && draft.issuer && draft.documentType.trim()
    && draft.fields.passport_number?.trim() && draft.reason.trim().length >= 3);
  return { opened, draft, change, changeField, selectFile, preview, imageFailed, confirmed, setConfirmed,
    pending, error, canSave, submit };
}

export type CompanyDocumentUploadController = ReturnType<typeof useCompanyDocumentUpload>;

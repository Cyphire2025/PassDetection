"use client";

import { useId, useRef, useState } from "react";
import { Upload, X } from "lucide-react";
import { Button } from "@/components/ui";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import type { DocumentPassengerReviewRow, ManualDocumentReplacement } from "@/types/document-distribution.types";
import { reviewRowDocuments } from "./document-workspace-model";

export interface ManualPassengerDocumentDialogProps {
  row: DocumentPassengerReviewRow;
  mode: "add" | "replace";
  pending: boolean;
  error: string | null;
  onClose: () => void;
  onUpload: (file: File, replacements: ManualDocumentReplacement[]) => void;
}

export function ManualPassengerDocumentDialog({ row, mode, pending, error, onClose, onUpload }: ManualPassengerDocumentDialogProps) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const documents = reviewRowDocuments(row);
  const [file, setFile] = useState<File | null>(null);
  const [replacementId, setReplacementId] = useState(documents[0]?.id ?? "");
  const replacement = documents.find(document => document.id === replacementId);
  const replacing = mode === "replace";
  const handleKeyDown = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: !pending, onClose });
  return <div className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-900/50 p-4">
    <div ref={dialogRef} onKeyDown={handleKeyDown} role="dialog" aria-modal="true" aria-labelledby={titleId} className="max-h-[90dvh] w-full max-w-lg overflow-y-auto rounded-xl bg-white p-5 shadow-xl">
      <div className="flex items-center justify-between gap-3">
        <h2 id={titleId} className="text-lg font-semibold">{replacing ? "Replace document" : "Upload document"}</h2>
        <Button type="button" variant="ghost" size="icon" aria-label="Close document upload" disabled={pending} onClick={onClose}><X className="h-5 w-5" /></Button>
      </div>
      <p className="mt-3 font-semibold text-slate-900">{row.passenger_name}</p>
      <p className="text-sm text-slate-600">Passport: {row.passport_number || "Not set"}</p>
      <p className="mt-3 text-sm text-slate-600">Your PDF will be assigned directly to this passenger and saved.</p>
      {replacing && <label className="mt-4 block text-sm font-medium text-slate-700">
        Document to replace
        <select aria-label="Document to replace" value={replacementId} disabled={pending} onChange={event => setReplacementId(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 p-2">
          {documents.map(document => <option key={document.id} value={document.id}>{document.original_filename}</option>)}
        </select>
        <span className="mt-2 block text-xs font-normal text-slate-500">The previous file and sending history are retained. Other passengers who share it keep their assignment.</span>
      </label>}
      <label className="mt-4 block text-sm font-medium text-slate-700">
        Choose PDF
        <input data-dialog-initial-focus type="file" accept="application/pdf,.pdf" disabled={pending} onChange={event => setFile(event.target.files?.[0] ?? null)} className="mt-2 block w-full text-sm" />
      </label>
      {replacing && !replacement?.updated_at && <p role="alert" className="mt-3 text-sm text-red-700">Refresh the document list before replacing this PDF.</p>}
      {error && <p role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      <div className="mt-5 flex justify-end gap-3">
        <Button type="button" variant="secondary" disabled={pending} onClick={onClose}>Cancel</Button>
        <Button type="button" disabled={!file || pending || (replacing && !replacement?.updated_at)} isLoading={pending} onClick={() => {
          if (!file || (replacing && !replacement?.updated_at)) return;
          onUpload(file, replacing && replacement?.updated_at ? [{ id: replacement.id, updated_at: replacement.updated_at }] : []);
        }}><Upload className="h-4 w-4" />{replacing ? "Replace and save" : "Upload and save"}</Button>
      </div>
    </div>
  </div>;
}

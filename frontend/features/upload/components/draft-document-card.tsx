"use client";
import { Camera, CheckCircle2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { DraftSide } from "@/features/travellers/api/returning-draft.api";
import type { ReturningDocument } from "@/features/travellers/types";
import { returningApi } from "@/features/travellers/api/returning.api";
import type { DraftDocumentInputs } from "../services/draft-input-contract";
import { PUBLIC_UPLOAD_ACCEPT } from "../services/public-upload-file";
import { DOCUMENT_PREVIEW_LABELS } from "../services/document-preview-order";
import { FreshDocumentPreview } from "./fresh-document-preview";
import { SelectedDocumentPreview } from "./selected-document-preview";
import { DocumentProcessingFrame } from "./document-processing-frame";

type Props = {
  side: DraftSide; label: string; state: DraftDocumentInputs; selected?: File; saved?: ReturningDocument;
  status?: string; canFile: boolean; canCamera: boolean; disabled: boolean;
  onUpload: (file: File) => void; onCamera: () => void;
};
export function DraftDocumentCard({ side, label, state, selected, saved, status, canFile, canCamera, disabled, onUpload, onCamera }: Props) {
  const document = state.draft?.documents.find((item) => item.side === side);
  const present = Boolean(selected || document || saved?.available);
  const imageLabel = DOCUMENT_PREVIEW_LABELS[side];
  return <div className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5" data-document-side={side}>
    <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900">{present && <CheckCircle2 className="h-4 w-4 text-emerald-600" />}{label}</h3>
    {(canFile || canCamera) && <div className="mt-3 flex flex-wrap gap-2">
      {canFile && <label className={`relative inline-flex min-h-11 items-center gap-2 rounded-xl border border-blue-200 px-4 py-2 text-sm font-medium text-blue-700 ${disabled ? "opacity-50" : "hover:bg-blue-50"}`}><Upload className="h-4 w-4" />{present ? "Replace image" : "Choose file"}<input type="file" className="absolute inset-0 w-full cursor-pointer opacity-0 focus-visible:opacity-100" aria-label={`Upload ${label.toLowerCase()}`} accept={PUBLIC_UPLOAD_ACCEPT} disabled={disabled} onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) onUpload(file); }} /></label>}
      {canCamera && <Button type="button" variant="secondary" disabled={disabled} onClick={onCamera}><Camera className="mr-2 h-4 w-4" />Use camera</Button>}
    </div>}
    {!present && <p className="mt-3 text-xs leading-5 text-slate-500">{side === "photo" ? "A clear, recent photo with a plain background." : "Include the whole page, with clear text and no glare. Files up to 2 MB."}</p>}
    {present && <div className="mt-3"><DocumentProcessingFrame status={status}>
      {selected ? <SelectedDocumentPreview file={selected} label={imageLabel} /> : document ? <FreshDocumentPreview key={document.id} id={document.id} label={imageLabel} api={state.api} /> : saved && <FreshDocumentPreview key={saved.id} id={saved.id} label={imageLabel} api={returningApi} />}
    </DocumentProcessingFrame></div>}
    {side === "back" && state.draft?.ecr_status === "failed" && <p role="alert" className="mt-3 text-sm text-amber-800">We couldn’t check ECR clearly. Replace the address page with a readable image.</p>}
  </div>;
}

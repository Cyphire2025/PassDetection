"use client";

import { useEffect, useId, useRef, useState } from "react";
import { ExternalLink, FileCheck2, X } from "lucide-react";
import { Button } from "@/components/ui";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import type { DocumentDistributionLane } from "../config/document-distribution-lanes";

interface DocumentManualReviewDialogProps {
  file: File;
  lane: DocumentDistributionLane;
  reason: string;
  pending: boolean;
  error: string | null;
  onClose: () => void;
  onApprove: () => void;
}

export function DocumentManualReviewDialog({
  file, lane, reason, pending, error, onClose, onApprove,
}: DocumentManualReviewDialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewOpened, setPreviewOpened] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const handleKeyDown = useModalKeyboardBoundary({
    dialogRef, isOpen: true, canClose: !pending, onClose,
  });

  useEffect(() => {
    const url = URL.createObjectURL(file.slice(0, file.size, "application/pdf"));
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      onKeyDown={handleKeyDown}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm"
    >
      <div className="max-h-[90dvh] w-full max-w-xl overflow-y-auto rounded-xl bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-4">
          <div>
            <h2 id={titleId} className="text-lg font-semibold text-slate-900">Review document type</h2>
            <p id={descriptionId} className="mt-1 text-sm text-slate-600">
              Preview the PDF, then confirm it belongs in {lane.title}.
            </p>
          </div>
          <Button type="button" variant="ghost" size="icon" aria-label="Close document review" onClick={onClose} disabled={pending}>
            <X className="h-5 w-5" aria-hidden="true" />
          </Button>
        </div>
        <div className="space-y-4 px-5 py-5">
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
            <p className="break-words text-sm font-semibold text-slate-900">{file.name}</p>
            <p className="mt-1 text-xs text-slate-600">{reason}</p>
            {previewUrl ? (
              <a
                href={previewUrl}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => setPreviewOpened(true)}
                data-dialog-initial-focus
                className="mt-3 inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
              >
                <ExternalLink className="h-4 w-4" aria-hidden="true" />
                Preview PDF in new tab
              </a>
            ) : <p role="status" className="mt-3 text-sm text-slate-500">Preparing PDF preview…</p>}
            <p className="mt-2 text-xs text-slate-500">Return to this dialog after reviewing the PDF.</p>
          </div>
          <p className="text-sm leading-6 text-slate-600">
            This approves the document type only. The system will still check for a confirmed
            passenger match in this group before accepting the PDF for upload.
          </p>
          <label className="flex items-start gap-3 rounded-lg border border-blue-100 bg-blue-50/50 p-3 text-sm text-slate-800">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 shrink-0 rounded border-slate-300"
              checked={confirmed}
              disabled={!previewOpened || pending}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            <span>I reviewed this PDF and confirm it is a {lane.uploadLabel} for this group.</span>
          </label>
          {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
        </div>
        <div className="flex flex-wrap justify-end gap-2 border-t border-slate-100 px-5 py-4">
          <Button type="button" variant="secondary" onClick={onClose} disabled={pending}>Cancel</Button>
          <Button type="button" onClick={onApprove} disabled={!previewOpened || !confirmed} isLoading={pending} className="h-auto min-h-9 whitespace-normal">
            <FileCheck2 className="h-4 w-4 shrink-0" aria-hidden="true" />
            Approve as {lane.title}
          </Button>
        </div>
      </div>
    </div>
  );
}

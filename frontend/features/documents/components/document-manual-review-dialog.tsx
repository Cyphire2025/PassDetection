"use client";

import { useEffect, useId, useRef, useState } from "react";
import { ExternalLink, FileCheck2, X } from "lucide-react";
import { Button } from "@/components/ui";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import type { DocumentDistributionLane } from "../config/document-distribution-lanes";

export interface DocumentManualReviewItem {
  fileIndex: number;
  file: File;
  reason: string;
}

export interface DocumentManualReviewProgress {
  completed: number;
  total: number;
  uploaded: number;
  rejected: number;
  phase?: "approving" | "uploading";
}

interface DocumentManualReviewDialogProps {
  items: readonly DocumentManualReviewItem[];
  lane: DocumentDistributionLane;
  pending: boolean;
  error: string | null;
  progress?: DocumentManualReviewProgress | null;
  onClose: () => void;
  onApprove: () => void;
}

export function DocumentManualReviewDialog({
  items, lane, pending, error, progress, onClose, onApprove,
}: DocumentManualReviewDialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const [confirmed, setConfirmed] = useState(false);
  const handleKeyDown = useModalKeyboardBoundary({
    dialogRef, isOpen: true, canClose: !pending, onClose,
  });

  const selectedCount = items.length;
  const uploading = progress?.phase === "uploading";
  const progressTotal = progress ? uploading ? progress.total - progress.rejected : progress.total : 0;
  const progressCompleted = progress ? uploading ? progress.uploaded : progress.completed : 0;
  const progressPercent = progressTotal > 0
    ? Math.min(100, Math.max(0, Math.round(progressCompleted / progressTotal * 100)))
    : 0;

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
            <h2 id={titleId} className="text-lg font-semibold text-slate-900">Approve selected PDFs</h2>
            <p id={descriptionId} className="mt-1 text-sm text-slate-600">
              {selectedCount} {selectedCount === 1 ? "PDF selected" : "PDFs selected"} for {lane.title}. Preview any file below before confirming.
            </p>
          </div>
          <Button type="button" variant="ghost" size="icon" aria-label="Close document review" onClick={onClose} disabled={pending}>
            <X className="h-5 w-5" aria-hidden="true" />
          </Button>
        </div>
        <div className="space-y-4 px-5 py-5">
          <ul aria-label="Selected PDFs" className="max-h-64 divide-y divide-slate-200 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50">
            {items.map((item) => <DocumentManualReviewFile key={item.fileIndex} item={item} />)}
          </ul>
          <p className="text-sm leading-6 text-slate-600">
            Approving confirms the document type and uploads the selected PDFs with a confirmed
            passenger match. Files without a confirmed match remain rejected. Your other files stay unchanged.
          </p>
          <label className="flex items-start gap-3 rounded-lg border border-blue-100 bg-blue-50/50 p-3 text-sm text-slate-800">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 shrink-0 rounded border-slate-300"
              checked={confirmed}
              disabled={pending || selectedCount === 0}
              onChange={(event) => setConfirmed(event.target.checked)}
              data-dialog-initial-focus
            />
            <span>
              I reviewed the selection and confirm {selectedCount === 1 ? "this PDF belongs" : "these PDFs belong"} in {lane.title} for this group.
            </span>
          </label>
          {progress && (
            <div className="space-y-2 rounded-lg border border-blue-100 bg-blue-50 p-3 text-sm text-blue-950">
              <div role="status" aria-live="polite" className="flex flex-wrap items-center justify-between gap-2">
                <span>
                  {pending
                    ? uploading ? "Uploading selected PDFs" : "Checking selected approvals"
                    : uploading ? "Selected upload progress" : "Selected approval progress"}
                </span>
                <span className="tabular-nums">{progressCompleted} of {Math.max(0, progressTotal)}</span>
              </div>
              <div
                role="progressbar"
                aria-label={uploading ? "Selected PDF upload progress" : "Selected PDF approval progress"}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={progressPercent}
                className="h-2 overflow-hidden rounded-full bg-white"
              >
                <div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${progressPercent}%` }} />
              </div>
              <p className="text-xs text-blue-800">
                {progress.uploaded} uploaded{progress.rejected > 0 ? ` · ${progress.rejected} could not be accepted` : ""}
              </p>
            </div>
          )}
          {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
        </div>
        <div className="flex flex-wrap justify-end gap-2 border-t border-slate-100 px-5 py-4">
          <Button type="button" variant="secondary" onClick={onClose} disabled={pending}>Cancel</Button>
          <Button type="button" onClick={onApprove} disabled={!confirmed || selectedCount === 0} isLoading={pending} className="h-auto min-h-9 whitespace-normal">
            <FileCheck2 className="h-4 w-4 shrink-0" aria-hidden="true" />
            Approve &amp; upload selected ({selectedCount})
          </Button>
        </div>
      </div>
    </div>
  );
}

function DocumentManualReviewFile({ item }: { item: DocumentManualReviewItem }) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  useEffect(() => {
    const url = URL.createObjectURL(item.file.slice(0, item.file.size, "application/pdf"));
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [item.file]);

  return (
    <li className="flex flex-col gap-2 p-3 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
      <div className="min-w-0">
        <p className="break-words text-sm font-semibold text-slate-900">{item.file.name}</p>
        <p className="mt-1 text-xs text-slate-600">{item.reason}</p>
      </div>
      {previewUrl ? (
        <a
          href={previewUrl}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Preview ${item.file.name} in a new tab`}
          className="inline-flex w-fit shrink-0 items-center gap-1.5 rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
        >
          <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
          Preview PDF
        </a>
      ) : <span className="text-xs text-slate-500">Preparing preview…</span>}
    </li>
  );
}

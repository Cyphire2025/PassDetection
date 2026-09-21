"use client";

import { useId, useRef, useState } from "react";
import { FileCheck2, FileWarning, Replace, X } from "lucide-react";
import { Button } from "@/components/ui";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import type {
  DocumentFilenameConflict,
  DocumentFilenameConflictChoice,
} from "../services/document-filename-conflicts";

interface DocumentFilenameConflictDialogProps {
  conflict: DocumentFilenameConflict;
  error?: string | null;
  onDecision: (choice: DocumentFilenameConflictChoice, applyToRemaining: boolean) => void;
  onCancel: () => void;
}

function fileSize(bytes: number) {
  return bytes >= 1024 * 1024
    ? `${(bytes / (1024 * 1024)).toFixed(1)} MB`
    : `${Math.max(1, Math.ceil(bytes / 1024))} KB`;
}

/** Mount with key={conflict.selectedIndex} to reset the apply-to-remaining checkbox. */
export function DocumentFilenameConflictDialog({
  conflict, error, onDecision, onCancel,
}: DocumentFilenameConflictDialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const [applyToRemaining, setApplyToRemaining] = useState(false);
  const onKeyDown = useModalKeyboardBoundary({
    dialogRef, isOpen: true, canClose: true, onClose: onCancel,
  });
  const previousFile = conflict.previousSelectedFile;

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      onKeyDown={onKeyDown}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm"
    >
      <div className="max-h-[90dvh] w-full max-w-xl overflow-y-auto rounded-xl bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-4">
          <div>
            <h2 id={titleId} className="text-lg font-semibold text-slate-900">This filename already exists</h2>
            <p className="mt-1 text-xs text-slate-500">Conflict {conflict.conflictNumber} of {conflict.totalConflicts}</p>
          </div>
          <Button type="button" variant="ghost" size="icon" aria-label="Cancel filename review" onClick={onCancel}>
            <X className="h-5 w-5" aria-hidden="true" />
          </Button>
        </div>
        <div className="space-y-4 px-5 py-5">
          <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4">
            <FileWarning className="mt-0.5 h-5 w-5 shrink-0 text-amber-700" aria-hidden="true" />
            <div>
              <p className="break-words text-sm font-semibold text-slate-900">{conflict.filename}</p>
              <p id={descriptionId} className="mt-1 text-sm text-slate-700">
                {previousFile
                  ? "Another PDF with this exact filename is already selected for checking."
                  : "A PDF with this exact filename is already saved in this group and document section."}
              </p>
              <p className="mt-2 text-xs text-slate-600">Incoming PDF: {fileSize(conflict.incomingFile.size)}</p>
              {previousFile && <p className="mt-1 text-xs text-slate-600">Previously selected PDF: {fileSize(previousFile.size)}</p>}
              {conflict.savedDocumentCount > 1 && (
                <p className="mt-1 text-xs text-slate-600">The saved filename has {conflict.savedDocumentCount} passenger assignments.</p>
              )}
            </div>
          </div>
          <p className="text-sm leading-6 text-slate-600">
            {previousFile
              ? "Replace uses the incoming PDF instead of the previously selected copy. Keep original skips this incoming copy."
              : "Replace checks the incoming PDF and replaces the saved copy only after it passes and uploads successfully. Keep original skips this incoming PDF."}
          </p>
          {previousFile && conflict.savedDocumentCount > 0 && (
            <p className="text-sm leading-6 text-slate-600">The saved PDF stays in place until the chosen replacement passes checking and uploads successfully.</p>
          )}
          {conflict.remainingConflictCount > 0 && (
            <label className="flex items-start gap-3 rounded-lg border border-slate-200 p-3 text-sm text-slate-700">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 shrink-0 rounded border-slate-300"
                checked={applyToRemaining}
                onChange={(event) => setApplyToRemaining(event.target.checked)}
              />
              <span>Do this for the remaining {conflict.remainingConflictCount} filename {conflict.remainingConflictCount === 1 ? "conflict" : "conflicts"}.</span>
            </label>
          )}
          {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
        </div>
        <div className="flex flex-wrap justify-end gap-2 border-t border-slate-100 px-5 py-4">
          <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>
          <Button type="button" variant="secondary" data-dialog-initial-focus onClick={() => onDecision("keep_original", applyToRemaining)}>
            <FileCheck2 className="h-4 w-4" aria-hidden="true" />
            Keep original
          </Button>
          <Button type="button" onClick={() => onDecision("replace", applyToRemaining)}>
            <Replace className="h-4 w-4" aria-hidden="true" />
            Replace
          </Button>
        </div>
      </div>
    </div>
  );
}

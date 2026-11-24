import { useRef } from "react";
import { X, Trash2 } from "lucide-react";
import { Button } from "@/components/ui";
import { useModalKeyboardBoundary } from "@/components/ui/modal";

type AbortIncompleteUploadDialogProps = {
  uploadCount: number;
  pending: boolean;
  error: Error | null;
  onClose: () => void;
  onConfirm: () => void;
};

export function AbortIncompleteUploadDialog({
  uploadCount,
  pending,
  error,
  onClose,
  onConfirm,
}: AbortIncompleteUploadDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const handleKeyDown = useModalKeyboardBoundary({
    dialogRef,
    isOpen: true,
    canClose: !pending,
    onClose,
  });
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div
        ref={dialogRef}
        onKeyDown={handleKeyDown}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="abort-incomplete-upload-title"
        className="w-full max-w-lg overflow-hidden rounded-xl bg-white shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-6 py-5">
          <div>
            <h2 id="abort-incomplete-upload-title" className="text-lg font-semibold text-slate-900">
              Discard incomplete {uploadCount === 1 ? "upload" : "uploads"}?
            </h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              This removes PDFs and partial matches from {uploadCount === 1 ? "this unfinished upload" : `these ${uploadCount} unfinished uploads`}. If an upload has already replaced saved PDFs, its successfully uploaded copies are kept for review. Other completed and saved document lists stay unchanged.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close dialog"
            className="rounded-full p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
            disabled={pending}
            onClick={onClose}
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="space-y-3 px-6 py-5">
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            After cleanup, you can choose a new PDF selection and Save List will no longer be blocked by these unfinished uploads.
          </div>
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error.message}
            </div>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-100 px-6 py-4">
          <Button type="button" variant="secondary" data-dialog-initial-focus onClick={onClose} disabled={pending}>
            Keep upload
          </Button>
          <Button type="button" variant="danger" onClick={onConfirm} isLoading={pending}>
            <Trash2 className="h-4 w-4" />
            Discard incomplete {uploadCount === 1 ? "upload" : "uploads"}
          </Button>
        </div>
      </div>
    </div>
  );
}

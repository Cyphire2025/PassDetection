import { useRef } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui";
import { useModalKeyboardBoundary } from "@/components/ui/modal";

type RemoveAssignmentsDialogProps = {
  passengerCount: number;
  documentCount: number;
  pending: boolean;
  error: Error | null;
  onClose: () => void;
  onKeepFiles: () => void;
  onDeleteFiles: () => void;
};

export function RemoveAssignmentsDialog({
  passengerCount,
  documentCount,
  pending,
  error,
  onClose,
  onKeepFiles,
  onDeleteFiles,
}: RemoveAssignmentsDialogProps) {
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
        aria-labelledby="remove-assignments-title"
        className="w-full max-w-xl overflow-hidden rounded-xl bg-white shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-6 py-5">
          <div>
            <h2 id="remove-assignments-title" className="text-lg font-semibold text-slate-900">
              Remove document assignments?
            </h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              This removes {documentCount} saved document{documentCount === 1 ? "" : "s"} from{" "}
              {passengerCount} passenger{passengerCount === 1 ? "" : "s"}. Choose what should happen
              to the saved PDF files.
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
          <button
            type="button"
            disabled={pending}
            onClick={onKeepFiles}
            className="w-full rounded-xl border border-blue-200 bg-blue-50 p-4 text-left transition hover:border-blue-300 disabled:pointer-events-none disabled:opacity-50"
          >
            <div className="font-semibold text-blue-950">Keep saved PDFs</div>
            <div className="mt-1 text-sm leading-5 text-blue-800">
              Remove the passenger assignments and move the PDFs to Needs assignment so they can
              be assigned again later.
            </div>
          </button>
          <button
            type="button"
            disabled={pending}
            onClick={onDeleteFiles}
            className="w-full rounded-xl border border-red-200 bg-red-50 p-4 text-left transition hover:border-red-300 disabled:pointer-events-none disabled:opacity-50"
          >
            <div className="font-semibold text-red-950">Delete saved PDFs</div>
            <div className="mt-1 text-sm leading-5 text-red-800">
              Remove the assignments and permanently delete these saved document files. Delivery
              history remains recorded for audit purposes.
            </div>
          </button>
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error.message}
            </div>
          )}
        </div>

        <div className="flex justify-end border-t border-slate-100 px-6 py-4">
          <Button type="button" variant="secondary" data-dialog-initial-focus onClick={onClose} disabled={pending}>
            Cancel
          </Button>
        </div>
      </div>
    </div>
  );
}

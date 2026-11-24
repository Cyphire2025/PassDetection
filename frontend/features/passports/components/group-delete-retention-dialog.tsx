import { useRef } from "react";
import { XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import type { UploadLinkResponse } from "../api/upload-links.api";

export function GroupDeleteRetentionDialog({
  group,
  isLoading,
  error,
  onClose,
  onKeepData,
  onDeleteData,
}: {
  group: UploadLinkResponse | null;
  isLoading: boolean;
  error: string | null;
  onClose: () => void;
  onKeepData: () => void;
  onDeleteData: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const handleDialogKeyDown = useModalKeyboardBoundary({
    dialogRef,
    isOpen: Boolean(group),
    canClose: !isLoading,
    onClose,
  });
  if (!group) return null;

  return (
    <div
      ref={dialogRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-archived-group-title"
      aria-describedby="delete-archived-group-description"
      aria-busy={isLoading}
      onKeyDown={handleDialogKeyDown}

    >
      <div
        className="max-h-[calc(100dvh-2rem)] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white shadow-2xl animate-in fade-in zoom-in-95 duration-200"
      >
        <div className="border-b border-slate-100 px-6 py-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 id="delete-archived-group-title" className="text-lg font-semibold text-slate-900">Delete Archived Group</h2>
              <p id="delete-archived-group-description" className="mt-1 text-sm leading-6 text-slate-600">
                Choose how passport records for <span className="font-semibold text-slate-900">{group.name}</span> should be handled.
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              disabled={isLoading}
              className="rounded-full p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              aria-label="Close dialog"

            >
              <XCircle className="h-5 w-5" />
            </button>
          </div>
        </div>

        {error && (
          <div role="alert" className="mx-6 mt-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            <p className="font-semibold">Could not delete this group</p>
            <p className="mt-1">{error}</p>
          </div>
        )}

        <div className="grid gap-4 p-6 md:grid-cols-2">
          <button
            type="button"
            disabled={isLoading}
            onClick={onKeepData}
            className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-left transition hover:border-blue-300 hover:bg-blue-100 disabled:opacity-60"

          >
            <div className="text-base font-semibold text-blue-950">Keep passport records</div>
            <p className="mt-2 text-sm leading-6 text-blue-800">
              Move this group to Old Data. Managers will no longer see it, but Super Admin can access the saved group folder and its passport records later.
            </p>
          </button>

          <button
            type="button"
            disabled={isLoading}
            onClick={onDeleteData}
            className="rounded-xl border border-red-200 bg-red-50 p-4 text-left transition hover:border-red-300 hover:bg-red-100 disabled:opacity-60"

          >
            <div className="text-base font-semibold text-red-950">Delete passport records</div>
            <p className="mt-2 text-sm leading-6 text-red-800">
              Permanently remove uploaded passport files and extracted records.
            </p>
          </button>
        </div>

        <div className="flex items-center justify-end gap-4 border-t border-slate-100 px-6 py-4">
          {isLoading && <p role="status" className="text-sm text-slate-600">Deleting group…</p>}
          <Button
            type="button"
            variant="secondary"
            onClick={onClose}
            disabled={isLoading}
            data-dialog-initial-focus

          >
            Cancel
          </Button>
        </div>
      </div>
    </div>
  );
}

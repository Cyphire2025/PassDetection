"use client";

import { useId, useRef } from "react";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { Button } from "@/components/ui";
import type { ManagerAccount } from "../../api/operations.api";

export function DeleteManagerDialog({
  manager,
  deleteOwnedData,
  isLoading,
  onDeleteOwnedDataChange,
  onClose,
  onConfirm,
}: {
  manager: ManagerAccount | null;
  deleteOwnedData: boolean;
  isLoading: boolean;
  onDeleteOwnedDataChange: (value: boolean) => void;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const handleKeyDown = useModalKeyboardBoundary({ dialogRef, isOpen: manager !== null, canClose: !isLoading, onClose });
  if (!manager) return null;

  return (
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId} onKeyDown={handleKeyDown} className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="max-h-[90dvh] w-full max-w-xl overflow-y-auto rounded-xl bg-white shadow-2xl animate-in fade-in zoom-in-95 duration-200">
        <div className="border-b border-slate-100 px-6 py-5">
          <h2 id={titleId} className="text-lg font-semibold text-slate-900">Delete Manager Account</h2>
          <p id={descriptionId} className="mt-2 text-sm leading-6 text-slate-600">
            This will remove the sign-in access for {manager.full_name}. By default, groups and passport records created by
            this manager are retained under administrator ownership and can be reassigned later.
          </p>
        </div>
        <div className="space-y-4 px-6 py-5">
          <label className="flex gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900">
            <input
              type="checkbox"
              className="mt-1 h-4 w-4 rounded border-red-300 text-red-600 focus:ring-red-500"
              disabled={isLoading}
              checked={deleteOwnedData}
              onChange={(event) => onDeleteOwnedDataChange(event.target.checked)}
            />
            <span>
              <span className="block font-semibold">Also permanently delete manager-owned operational data</span>
              <span className="mt-1 block text-red-800">
                Deletes groups, passport submissions, uploaded images, and processing records originally created by this
                manager. This cannot be undone.
              </span>
            </span>
          </label>
        </div>
        <div className="flex justify-end gap-3 border-t border-slate-100 px-6 py-4">
          <Button type="button" variant="secondary" onClick={onClose} disabled={isLoading} data-dialog-initial-focus>
            Cancel
          </Button>
          <Button type="button" variant="danger" onClick={onConfirm} isLoading={isLoading}>
            Delete Manager
          </Button>
        </div>
      </div>
    </div>
  );
}

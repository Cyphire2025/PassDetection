"use client";

import { useId, useRef } from "react";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import type { FormEvent } from "react";
import { UserPlus, X } from "lucide-react";
import { Button, Card, CardContent, Input } from "@/components/ui";

export function CreateManagerDialog({
  form,
  formError,
  isLoading,
  onClose,
  onFormChange,
  onSubmit,
}: {
  form: { full_name: string; email: string; };
  formError: string | null;
  isLoading: boolean;
  onClose: () => void;
  onFormChange: React.Dispatch<React.SetStateAction<{ full_name: string; email: string; }>>;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const handleDialogKeyDown = useModalKeyboardBoundary({
    dialogRef,
    isOpen: true,
    canClose: !isLoading,
    onClose,
  });
  return (
    <div
      ref={dialogRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      onKeyDown={handleDialogKeyDown}
    >
      <Card className="max-h-[90dvh] w-full max-w-lg overflow-y-auto shadow-2xl">
        <CardContent className="space-y-5 p-6">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-3">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600 ring-1 ring-blue-100">
                <UserPlus className="h-5 w-5" />
              </span>
              <div className="min-w-0">
                <h2 id={titleId} className="text-base font-semibold text-slate-900">Create Manager</h2>
                <p id={descriptionId} className="mt-0.5 text-sm leading-5 text-slate-500">Managers can create groups and work on assigned groups.</p>
              </div>
            </div>
            <button type="button" className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700" onClick={onClose} disabled={isLoading}>
              <X className="h-5 w-5" />
              <span className="sr-only">Close</span>
            </button>
          </div>

          <form className="space-y-4" onSubmit={onSubmit}>
            <Input
              label="Full name"
              placeholder="Example: Rahul Mehta"
              value={form.full_name}
              onChange={(event) => onFormChange((current) => ({ ...current, full_name: event.target.value }))}
              required
              data-dialog-initial-focus
            />
            <Input
              label="Email"
              type="email"
              placeholder="manager@company.com"
              value={form.email}
              onChange={(event) => onFormChange((current) => ({ ...current, email: event.target.value }))}
              required
            />
            <p className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-xs leading-5 text-blue-800">
              A single-use activation link will be shown once. The manager chooses their own password and enrolls MFA before a dashboard session is issued.
            </p>
            {formError && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{formError}</div>}
            <div className="flex justify-end gap-3 pt-1">
              <Button type="button" variant="secondary" onClick={onClose} disabled={isLoading}>Cancel</Button>
              <Button type="submit" isLoading={isLoading}>
                Create Manager
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}


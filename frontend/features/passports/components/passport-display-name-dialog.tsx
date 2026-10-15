"use client";

import { useId, useRef, useState } from "react";
import { X } from "lucide-react";
import { Button, Input } from "@/components/ui";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import type { DisplayNamePatch } from "../api/display-name.api";
import { useDisplayNameEditor } from "../hooks/use-display-name";
import { mutationErrorMessage } from "./passport-group-model";

export function PassportDisplayNameDialog({ id, groupId, onClose }: {
  id: string; groupId: string; onClose: () => void;
}) {
  const { query, mutation } = useDisplayNameEditor(id, groupId);
  const [editorVersion, setEditorVersion] = useState(0);
  const [isReloading, setIsReloading] = useState(false);
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const isBusy = mutation.isPending || isReloading;
  const onKeyDown = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: !isBusy, onClose });
  const reload = async () => {
    setIsReloading(true);
    try {
      const latest = await query.refetch();
      if (latest.error || !latest.data) throw latest.error || new Error("The latest name could not be loaded.");
      setEditorVersion((version) => version + 1);
    } finally { setIsReloading(false); }
  };
  return (
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId}
      onKeyDown={onKeyDown} className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-sm">
      <div className="w-full max-w-lg overflow-hidden rounded-2xl bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 p-5">
          <div>
            <h2 id={titleId} className="text-lg font-semibold text-slate-900">Edit display name</h2>
            <p id={descriptionId} className="mt-1 text-sm text-slate-600">Change the name shown in passenger lists and document distribution. Passport details and assigned documents stay unchanged.</p>
          </div>
          <Button type="button" variant="ghost" aria-label="Close display name editor" disabled={isBusy} onClick={onClose} data-dialog-initial-focus>
            <X className="h-4 w-4" />
          </Button>
        </div>
        {query.isPending ? <p role="status" className="p-5 text-sm">Loading the saved name…</p> :
          !query.data || query.data.group_id !== groupId ? (
            <div className="space-y-3 p-5">
              <p role="alert" className="text-sm text-red-700">The passenger could not be loaded in this group.</p>
              <Button type="button" variant="secondary" onClick={() => void query.refetch()}>Retry loading name</Button>
            </div>
          ) : (
            <DisplayNameForm key={editorVersion} initialName={query.data.display_name || query.data.client_name} updatedAt={query.data.updated_at}
              isBusy={isBusy} onSave={mutation.mutateAsync} onClose={onClose} onReload={reload} />
          )}
      </div>
    </div>
  );
}

function DisplayNameForm({ initialName, updatedAt, isBusy, onSave, onClose, onReload }: {
  initialName: string; updatedAt: string; isBusy: boolean;
  onSave: (body: DisplayNamePatch) => Promise<unknown>; onClose: () => void; onReload: () => Promise<void>;
}) {
  // Keep draft and revision together until an explicit reload; background cache
  // invalidation must never advance the optimistic lock underneath an edit.
  const [snapshot] = useState({ name: initialName, updatedAt });
  const [name, setName] = useState(initialName);
  const [feedback, setFeedback] = useState<{ message: string; conflict: boolean } | null>(null);
  const inFlight = useRef(false);
  const normalizedName = name.trim().replace(/\s+/g, " ");
  const canSave = Boolean(normalizedName) && normalizedName !== snapshot.name && !feedback?.conflict;
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSave || isBusy || inFlight.current) return;
    inFlight.current = true;
    setFeedback(null);
    try {
      await onSave({ display_name: normalizedName, expected_updated_at: snapshot.updatedAt });
      onClose();
    } catch (error) {
      const value = error as { status?: number; code?: string };
      setFeedback({ message: mutationErrorMessage(error, "The display name could not be saved."), conflict: value?.status === 409 || value?.code === "HTTP_409" });
    } finally { inFlight.current = false; }
  };
  return <form onSubmit={submit} aria-busy={isBusy}>
    <div className="space-y-4 p-5">
      <Input label="Display name" value={name} maxLength={255} required disabled={isBusy || feedback?.conflict}
        onChange={(event) => setName(event.target.value)} />
      <p className="text-xs leading-5 text-slate-500">For passengers with the same passport name, use Upload document on the intended passenger to assign a PDF directly.</p>
      {feedback && <div role="alert" className="space-y-2 rounded-lg bg-red-50 p-3 text-sm text-red-700">
        <p>{feedback.message}</p>
        {feedback.conflict && <Button type="button" variant="secondary" disabled={isBusy} onClick={async () => {
          try { await onReload(); }
          catch { setFeedback({ message: "The latest name could not be loaded. Your draft is still here; try reloading again.", conflict: true }); }
        }}>Reload latest name</Button>}
      </div>}
    </div>
    <div className="flex justify-end gap-3 border-t border-slate-200 p-5">
      <Button type="button" variant="secondary" disabled={isBusy} onClick={onClose}>Cancel</Button>
      <Button type="submit" disabled={!canSave || isBusy} isLoading={isBusy}>Save display name</Button>
    </div>
  </form>;
}

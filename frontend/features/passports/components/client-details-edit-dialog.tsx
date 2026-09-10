"use client";

import { useId, useRef, useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import type { ClientDetailsEditorResponse } from "../api/client-details.api";
import { useClientDetailsEditor, useUpdateClientDetails } from "../hooks/use-client-details";
import { buildClientDetailsPatch, clientDetailsError, clientDetailsValidation, createClientDetailsDraft } from "../utils/client-details-editor";

export function ClientDetailsEditDialog({ id, groupId, onClose }: {
  id: string; groupId: string; onClose: () => void;
}) {
  const query = useClientDetailsEditor(id);
  const mutation = useUpdateClientDetails(id, groupId);
  const [editorVersion, setEditorVersion] = useState(0);
  const [isReloading, setIsReloading] = useState(false);
  const isBusy = mutation.isPending || isReloading;
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const onKeyDown = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: !isBusy, onClose });
  const reload = async () => {
    setIsReloading(true);
    try {
      const latest = await query.refetch();
      if (latest.error || !latest.data) throw latest.error || new Error("The latest details are unavailable.");
      setEditorVersion((version) => version + 1);
    } finally { setIsReloading(false); }
  };
  return (
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} onKeyDown={onKeyDown}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/55 p-3 backdrop-blur-sm sm:p-6">
      <div className="flex max-h-[90dvh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
          <div>
            <h2 id={titleId} className="text-lg font-semibold text-slate-900">Edit client-provided group details</h2>
            <p className="mt-1 text-sm text-slate-600">Correct the saved values exactly. This does not change passport fields or reset the approval status.</p>
          </div>
          <Button variant="ghost" type="button" aria-label="Close details editor" disabled={isBusy} onClick={onClose} data-dialog-initial-focus>
            <X className="h-4 w-4" />
          </Button>
        </div>
        {query.isPending ? (
          <p role="status" className="p-6 text-sm text-slate-600">Loading the latest saved details…</p>
        ) : !query.data ? (
          <div className="space-y-3 p-6">
            <p role="alert" className="text-sm text-red-700">The current details could not be loaded. No changes have been made.</p>
            <Button type="button" variant="secondary" onClick={() => void query.refetch()}>Retry loading details</Button>
          </div>
        ) : (
          <ClientDetailsForm key={editorVersion} data={query.data} isSaving={isBusy} onSave={mutation.mutateAsync}
            onClose={onClose} onReload={reload} />
        )}
      </div>
    </div>
  );
}

function ClientDetailsForm({ data: initialData, isSaving, onSave, onClose, onReload }: {
  data: ClientDetailsEditorResponse;
  isSaving: boolean;
  onSave: (patch: ReturnType<typeof buildClientDetailsPatch>) => Promise<unknown>;
  onClose: () => void;
  onReload: () => Promise<void>;
}) {
  // Freeze the descriptor and optimistic-lock token alongside the draft. Even a
  // programmatic query invalidation cannot silently advance this edit session.
  // Only a successful, explicit Reload remounts the form with a new snapshot.
  const [data] = useState(initialData);
  const [draft, setDraft] = useState(() => createClientDetailsDraft(data));
  const [feedback, setFeedback] = useState<{ message: string; conflict: boolean } | null>(null);
  const inFlight = useRef(false);
  const patch = buildClientDetailsPatch(data, draft);
  const changed = Object.keys(patch).length > 1;
  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (inFlight.current || isSaving || !changed || feedback?.conflict) return;
    const validation = clientDetailsValidation(data, draft);
    if (validation) { setFeedback({ message: validation, conflict: false }); return; }
    inFlight.current = true;
    setFeedback(null);
    try { await onSave(patch); onClose(); }
    catch (error) { setFeedback(clientDetailsError(error)); }
    finally { inFlight.current = false; }
  };
  return (
    <form onSubmit={save} noValidate className="flex min-h-0 flex-col" aria-busy={isSaving}>
      <div className="space-y-4 overflow-y-auto px-5 py-4">
        <p className="rounded-lg bg-blue-50 p-3 text-xs leading-5 text-blue-900">Only edited values are saved. Labels and question options stay unchanged. WhatsApp matching refreshes after saving. Queued private document or QR deliveries for this group will need a fresh preview after a correction. Regular reminders are unchanged.</p>
        {feedback && <div role="alert" className="space-y-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          <p>{feedback.message}</p>
          {feedback.conflict && <Button type="button" variant="secondary" disabled={isSaving} onClick={async () => {
            try { await onReload(); }
            catch { setFeedback({ conflict: true, message: "The latest details could not be loaded. Your draft is still here; retry reloading before saving." }); }
          }}>Reload latest details</Button>}
        </div>}
        <fieldset disabled={isSaving || feedback?.conflict} className="grid gap-4 sm:grid-cols-2">
          <legend className="sr-only">Saved client details</legend>
          {data.fields.map(({ key, ...field }) => <ClientDetailInput key={key} {...field} value={draft.fields[key] ?? ""}
            required={field.required && draft.fields[key] !== (field.value ?? "")}
            onChange={(value) => setDraft((current) => ({ ...current, fields: { ...current.fields, [key]: value } }))} />)}
          {data.custom_answers.map((field) => <ClientDetailInput key={`question:${field.question_id}`} {...field} type={field.options.length ? "select" : "text"} value={draft.questions[field.question_id] ?? ""}
            required={field.required && draft.questions[field.question_id] !== (field.value ?? "")}
            onChange={(value) => setDraft((current) => ({ ...current, questions: { ...current.questions, [field.question_id]: value } }))} />)}
          {data.custom_detail_answers.map((field) => <ClientDetailInput key={`detail:${field.detail_id}`} {...field} type="text" options={[]} value={draft.details[field.detail_id] ?? ""}
            required={field.required && draft.details[field.detail_id] !== (field.value ?? "")}
            onChange={(value) => setDraft((current) => ({ ...current, details: { ...current.details, [field.detail_id]: value } }))} />)}
        </fieldset>
      </div>
      <div className="flex justify-end gap-3 border-t border-slate-200 px-5 py-4">
        <Button type="button" variant="secondary" disabled={isSaving} onClick={onClose}>Cancel</Button>
        <Button type="submit" isLoading={isSaving} disabled={!changed || Boolean(feedback?.conflict)}>Save corrections</Button>
      </div>
    </form>
  );
}

function ClientDetailInput({ label, value, required, type, options, max_length, onChange }: {
  label: string; value: string; required: boolean; type: string; options: string[]; max_length: number;
  onChange: (value: string) => void;
}) {
  const id = useId();
  if (type !== "select") return <Input label={label} value={value} type={type} maxLength={max_length} required={required} onChange={(event) => onChange(event.target.value)} />;
  return <div className="space-y-1.5">
    <label htmlFor={id} className="text-sm font-medium text-slate-700">{label}</label>
    <select id={id} value={value} required={required} onChange={(event) => onChange(event.target.value)}
      className="h-9 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 focus:border-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-600 disabled:opacity-60">
      <option value="">Not provided</option>
      {value && !options.includes(value) && <option value={value}>{value} (saved value)</option>}
      {options.map((option) => <option key={option} value={option}>{option}</option>)}
    </select>
  </div>;
}

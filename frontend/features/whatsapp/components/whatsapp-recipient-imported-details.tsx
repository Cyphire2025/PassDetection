"use client";

import { Pencil } from "lucide-react";
import { useState } from "react";
import type { WhatsAppRecipientDetailsEdit } from "../api/whatsapp.api";
import { readErrorMessage } from "./whatsapp-dialog-ui";
import { importedFieldLabel, visibleImportedFieldEntries } from "./whatsapp-recipient-roster-rows";

const READ_ONLY_FIELDS = new Set(["name", "phone_number", "duplicate_conflicting_fields"]);

export function RecipientImportedDetails({ name, importedFields, mergedContactId = null, sourceManaged = false, disabled, onSave }: {
  name: string | null;
  importedFields: Record<string, string>;
  mergedContactId?: string | null;
  sourceManaged?: boolean;
  disabled: boolean;
  onSave?: (details: WhatsAppRecipientDetailsEdit) => Promise<void>;
}) {
  const [draft, setDraft] = useState<WhatsAppRecipientDetailsEdit | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const entries = visibleImportedFieldEntries(importedFields);
  const editing = draft !== null;
  const edit = () => {
    setError(null);
    setDraft({ merged_contact_id: mergedContactId, expected_name: name, expected_imported_fields: { ...importedFields }, name: name ?? "", imported_fields: Object.fromEntries(entries.filter(([key]) => !READ_ONLY_FIELDS.has(key))) });
  };
  const save = async () => {
    if (!draft || !onSave || saving || disabled) return;
    setSaving(true);
    setError(null);
    try {
      await onSave(draft);
      setDraft(null);
    } catch (saveError) {
      setError(readErrorMessage(saveError, "Could not save the imported details."));
    } finally {
      setSaving(false);
    }
  };
  return (
    <details className="mt-1" data-recipient-details-editor>
      <summary className="cursor-pointer text-xs text-slate-500 hover:text-blue-700">
        {mergedContactId ? `${name || "Unnamed contact"} · saved contact details` : `${entries.length} imported ${entries.length === 1 ? "detail" : "details"}`}
      </summary>
      <div className="mt-2 min-w-56 space-y-3 rounded-lg border border-slate-200 bg-white p-3">
        {sourceManaged && <p className="max-w-sm text-xs leading-5 text-slate-500">These details sync from a linked passport group. Edit the person&apos;s record in that group to update them here.</p>}
        {!editing && !sourceManaged && onSave && <button type="button" disabled={disabled} onClick={edit} className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-50 disabled:opacity-50"><Pencil className="h-3.5 w-3.5" />Edit imported details</button>}
        {editing ? (
          <div className="space-y-3" role="group" aria-label={`Edit imported details for ${name || "contact"}`}>
            <label className="block text-xs font-semibold text-slate-600">Recipient name
              <input value={draft.name} autoFocus maxLength={100} disabled={saving || disabled} onChange={(event) => setDraft({ ...draft, name: event.target.value })} className="mt-1 block w-full rounded-md border border-slate-300 px-2 py-1.5 font-normal text-slate-900" />
            </label>
            {visibleImportedFieldEntries(draft.imported_fields).map(([key, value]) => <label key={key} className="block text-xs font-semibold text-slate-600">{importedFieldLabel(key)}
              <input value={value} maxLength={256} disabled={saving || disabled} onChange={(event) => setDraft({ ...draft, imported_fields: { ...draft.imported_fields, [key]: event.target.value } })} className="mt-1 block w-full rounded-md border border-slate-300 px-2 py-1.5 font-normal text-slate-900" />
            </label>)}
            <p className="max-w-sm text-xs leading-5 text-slate-500">To change the delivery number, use Edit WhatsApp number.</p>
            {error && <p role="alert" className="max-w-sm text-xs text-red-700">{error}</p>}
            <div className="flex gap-2">
              <button type="button" disabled={saving || disabled || !draft.name.trim()} onClick={() => void save()} className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">{saving ? "Saving…" : "Save details"}</button>
              <button type="button" disabled={saving} onClick={() => { setDraft(null); setError(null); }} className="rounded-md px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-100">Cancel</button>
            </div>
          </div>
        ) : (
          <dl className="grid gap-2">{entries.map(([key, value]) => <div key={key} className="min-w-0"><dt className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{importedFieldLabel(key)}</dt><dd className="break-words text-xs text-slate-700">{value}</dd></div>)}
            {entries.length === 0 && <div className="text-xs text-slate-500">No additional imported details.</div>}
          </dl>
        )}
      </div>
    </details>
  );
}

"use client";

import { useState } from "react";
import { Input } from "@/components/ui";
import type { WhatsAppRecipient } from "../api/whatsapp.api";
import { RecipientSelectionCheckbox } from "./whatsapp-recipient-selection";

export function PreviewRecipientPicker({ recipients, selectedIds, onChange, disabled = false }: {
  recipients: WhatsAppRecipient[];
  selectedIds: string[] | null;
  onChange: (ids: string[] | null) => void;
  disabled?: boolean;
}) {
  const [search, setSearch] = useState("");
  const eligibleIds = recipients.map((recipient) => recipient.id);
  const selected = new Set(selectedIds ?? eligibleIds);
  const selectedCount = eligibleIds.filter((id) => selected.has(id)).length;
  const matching = recipients.filter((recipient) =>
    `${recipient.name ?? ""} ${recipient.normalized_phone_number}`.toLowerCase().includes(search.trim().toLowerCase()),
  );

  return <fieldset disabled={disabled} className="min-w-0 space-y-3 rounded-xl border border-slate-200 bg-white p-3">
    <legend className="px-1 text-sm font-semibold text-slate-800">Recipients for this send</legend>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-sm text-slate-700">{selectedCount} of {recipients.length} eligible recipients selected</p>
      <div className="flex gap-3 text-xs font-semibold">
        <button type="button" onClick={() => onChange(null)} disabled={!eligibleIds.length} className="text-blue-700 hover:underline disabled:opacity-40">Select all</button>
        <button type="button" onClick={() => onChange([])} disabled={!selectedCount} className="text-slate-600 hover:underline disabled:opacity-40">Clear</button>
      </div>
    </div>
    <Input type="search" label="Search recipients by name or phone" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Name or phone number" />
    <p className="text-xs leading-5 text-slate-500">Click a recipient to select or deselect them. Selections stay selected when you search. Select all includes every eligible recipient.</p>
    <div className="max-h-64 divide-y divide-slate-100 overflow-y-auto rounded-lg border border-slate-200">
      {matching.map((recipient) => <label key={recipient.id} className="flex cursor-pointer items-start gap-3 p-3 text-sm hover:bg-slate-50">
        <RecipientSelectionCheckbox label={`${recipient.name || "Unnamed recipient"} ${recipient.normalized_phone_number}`} checked={selected.has(recipient.id)} onChange={(checked) => {
          const next = new Set(eligibleIds.filter((id) => selected.has(id)));
          if (checked) next.add(recipient.id); else next.delete(recipient.id);
          onChange([...next]);
        }} />
        <span className="min-w-0"><span className="block break-words font-medium text-slate-800">{recipient.name || "Unnamed recipient"}</span><span className="block break-all text-xs text-slate-500">{recipient.normalized_phone_number}</span></span>
      </label>)}
      {!matching.length && <p className="p-3 text-sm text-slate-500">No eligible recipients match this search.</p>}
    </div>
  </fieldset>;
}

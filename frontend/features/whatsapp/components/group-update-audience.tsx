"use client";

import { useId } from "react";
import { DOCUMENT_DISTRIBUTION_LANES } from "@/features/documents/config/document-distribution-lanes";
import type { GroupUpdateAudience, GroupUpdateRecipient } from "../api/group-updates.api";
import { MessageComposerSection } from "./whatsapp-message-composer-ui";

export function GroupUpdateAudienceFields({ audience, disabled, onChange }: {
  audience: GroupUpdateAudience; disabled: boolean; onChange: (value: GroupUpdateAudience) => void;
}) {
  const id = useId();
  const selectClass = "mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-3 text-sm disabled:opacity-50";
  return <MessageComposerSection title="Choose your audience" description="Use either filter or combine both. Only people in this group’s active, opted-in WhatsApp broadcasts are included.">
    <div className="grid gap-5 sm:grid-cols-2">
      <div><label htmlFor={`${id}-submission`} className="text-sm font-semibold">Submission status</label>
        <select id={`${id}-submission`} className={selectClass} value={audience.submission_status} disabled={disabled} onChange={event => onChange({ ...audience, submission_status: event.target.value as GroupUpdateAudience["submission_status"] })}>
          <option value="all">All people</option><option value="submitted">Submitted</option><option value="not_submitted">Not submitted</option>
        </select><p className="mt-2 text-xs leading-5 text-slate-500">Submitted: use the WhatsApp number supplied with their completed submission. Not submitted: use the imported broadcast number.</p>
      </div>
      <div><label htmlFor={`${id}-delivery`} className="text-sm font-semibold">Document delivery</label>
        <select id={`${id}-delivery`} className={selectClass} value={audience.document_status} disabled={disabled} onChange={event => onChange({ ...audience, document_status: event.target.value as GroupUpdateAudience["document_status"] })}>
          <option value="all">All — any document status</option><option value="sent">Sent</option><option value="pending">Pending</option>
        </select>
        <label htmlFor={`${id}-document`} className="mt-3 block text-sm font-medium">Document type</label>
        <select id={`${id}-document`} className={selectClass} value={audience.document_type} disabled={disabled || audience.document_status === "all"} onChange={event => onChange({ ...audience, document_type: event.target.value as GroupUpdateAudience["document_type"] })}>
          {Object.values(DOCUMENT_DISTRIBUTION_LANES).map(lane => <option key={lane.documentType} value={lane.documentType}>{lane.workflowLabel}</option>)}
        </select><p className="mt-2 text-xs leading-5 text-slate-500">Sent: every assigned PDF in this section was accepted for sending. Pending includes missing PDFs, failed sends, unknown outcomes and partly sent documents.</p>
      </div>
    </div>
  </MessageComposerSection>;
}

export function GroupUpdateRecipientRow({ row, selected, disabled, showDocuments, onChange }: {
  row: GroupUpdateRecipient; selected: boolean; disabled: boolean; showDocuments: boolean; onChange: (checked: boolean) => void;
}) {
  return <label className="flex items-start gap-3 border-b border-slate-100 p-4 last:border-0">
    <input type="checkbox" aria-label={`Select ${row.name}`} checked={selected} disabled={disabled || !row.eligible} onChange={event => onChange(event.target.checked)} className="mt-1 h-4 w-4" />
    <span className="min-w-0 flex-1"><span className="block text-sm font-semibold text-slate-900">{row.name}</span>
      <span className="mt-1 block text-sm text-slate-600">{row.phone_number ?? "No valid WhatsApp number"}</span>
      <span className="mt-1 block text-xs text-slate-500">{row.phone_source === "submitted" ? "Submitted WhatsApp number" : "Imported broadcast number"} · {row.submission_status === "submitted" ? "Submitted" : row.submission_status === "not_submitted" ? "Not submitted" : "Match needs review"}</span>
      {showDocuments ? <span className="mt-1 block text-xs text-slate-500">{row.document_count ? `${row.confirmed_count}/${row.document_count} documents sent` : "No document assigned"}</span> : null}
      {row.reason ? <span className="mt-1 block text-xs text-amber-800">{row.reason}</span> : null}
      {row.latest_update_status ? <span className="mt-1 block text-xs text-slate-500">Last update: {row.latest_update_status.replaceAll("_", " ")}</span> : null}
    </span>
  </label>;
}

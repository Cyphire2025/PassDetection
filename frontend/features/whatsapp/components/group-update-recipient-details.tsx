"use client";

import { formatDateTime } from "@/lib/utils/format";
import { useState } from "react";
import type { GroupUpdateRecipient } from "../api/group-updates.api";
import { documentsSent, updateStatusLabel, UPDATE_ACCEPTED } from "../utils/group-update-audience";
import { visibleImportedFieldEntries, importedFieldLabel } from "./whatsapp-recipient-roster-rows";

export function UpdateStatusBadge({ status }: { status: string | null | undefined }) {
  const color = status && UPDATE_ACCEPTED.has(status) ? "bg-emerald-50 text-emerald-700" : status === "failed" ? "bg-red-50 text-red-700" : status === "delivery_unknown" ? "bg-amber-50 text-amber-800" : status === "queued" || status === "processing" ? "bg-blue-50 text-blue-700" : "bg-slate-100 text-slate-600";
  return <span className={`inline-flex rounded-full px-2.5 py-1 text-[11px] font-semibold ${color}`}>{updateStatusLabel(status)}</span>;
}

export function GroupUpdateRecipientDetails({ row, documentLabel }: { row: GroupUpdateRecipient; documentLabel: string }) {
  const [expanded, setExpanded] = useState(false);
  const entries = visibleImportedFieldEntries(row.imported_details);
  const attempt = row.latest_update;
  return <details onToggle={event => setExpanded(event.currentTarget.open)} className="mt-2 text-xs text-slate-600"><summary className="w-fit cursor-pointer font-semibold text-blue-700 focus-visible:outline-blue-500">View recipient & update details</summary>
    {expanded && <div className="mt-3 space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
      <dl className="grid gap-3 sm:grid-cols-2">
        <Detail label="Document submission" value={row.submission_status === "submitted" ? "Submitted" : row.submission_status === "not_submitted" ? "Not submitted" : "Match needs review"} />
        <Detail label="WhatsApp number for this send" value={row.phone_number ?? "No valid number"} />
        <Detail label="Number source" value={row.phone_source === "submitted" ? "Traveller’s submitted WhatsApp number" : "Imported broadcast number"} />
        <Detail label={`${documentLabel} distribution`} value={documentsSent(row) ? `Sent (${row.confirmed_count}/${row.document_count} PDFs)` : row.document_count ? `Pending (${row.confirmed_count}/${row.document_count} PDFs sent)` : "Pending — no PDF assigned"} />
        {row.passport_number && <Detail label="Passport" value={row.passport_number} />}{row.email && <Detail label="Email" value={row.email} />}
        {entries.map(([key, value]) => <Detail key={key} label={importedFieldLabel(key)} value={value} />)}
      </dl>
      {attempt ? <div className="space-y-3 border-t border-slate-200 pt-3"><p className="font-semibold text-slate-800">Latest update attempt {row.update_attempt_count && row.update_attempt_count > 1 ? `· ${row.update_attempt_count} saved attempts` : ""}</p><dl className="grid gap-3 sm:grid-cols-2"><Detail label="Result" value={updateStatusLabel(attempt.status)} /><Detail label="Sent to" value={attempt.phone_number ?? "Not recorded"} /><Detail label="Requested" value={formatDateTime(attempt.created_at)} /><Detail label="Last status update" value={formatDateTime(attempt.status_updated_at)} /><Detail label="Template" value={attempt.template_name ?? "Not recorded"} />{attempt.provider_message_id && <Detail label="WhatsApp message ID" value={attempt.provider_message_id} />}</dl>{attempt.error && <p className="rounded-lg border border-red-200 bg-red-50 p-3 leading-5 text-red-800"><strong>Failure / review reason: </strong>{attempt.error}</p>}{attempt.message && <div><p className="mb-2 font-semibold text-slate-700">Saved update message</p><p className="whitespace-pre-wrap rounded-lg border border-slate-200 bg-white p-3 leading-5">{attempt.message}</p></div>}</div> : row.latest_update_status ? <p className="border-t pt-3">Latest result: {updateStatusLabel(row.latest_update_status)}{row.latest_update_at ? ` · ${formatDateTime(row.latest_update_at)}` : ""}</p> : <p className="border-t pt-3">No update has been sent to this traveller yet.</p>}
    </div>}
  </details>;
}

function Detail({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><dt className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</dt><dd className="mt-1 break-words text-xs text-slate-700 [overflow-wrap:anywhere]">{value}</dd></div>;
}

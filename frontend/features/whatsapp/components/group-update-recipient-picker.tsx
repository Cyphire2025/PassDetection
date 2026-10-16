"use client";

import { useState } from "react";
import { Input } from "@/components/ui";
import { formatDateTime } from "@/lib/utils/format";
import type { GroupUpdateRecipient } from "../api/group-updates.api";
import { documentsSent } from "../utils/group-update-audience";
import { GroupUpdateRecipientDetails, UpdateStatusBadge } from "./group-update-recipient-details";

export function GroupUpdateRecipientPicker({ rows, selectedKeys, disabled, loading, documentLabel, onChange }: {
  rows: GroupUpdateRecipient[]; selectedKeys: Set<string>; disabled: boolean; loading: boolean; documentLabel: string; onChange: (keys: string[]) => void;
}) {
  const [search, setSearch] = useState("");
  const [view, setView] = useState<"all" | "new" | "previous">("all");
  const [page, setPage] = useState(1);
  const eligible = rows.filter(row => row.eligible);
  const fresh = eligible.filter(row => !row.latest_update_status);
  const previous = rows.filter(row => row.latest_update_status);
  const chosen = eligible.filter(row => selectedKeys.has(row.audience_key));
  const query = search.trim().toLocaleLowerCase();
  const visible = rows.filter(row => (view === "all" || (view === "previous") === Boolean(row.latest_update_status)) && `${row.name} ${row.phone_number ?? ""} ${row.passport_number ?? ""} ${row.email ?? ""} ${Object.values(row.imported_details ?? {}).join(" ")}`.toLocaleLowerCase().includes(query));
  const pageCount = Math.max(1, Math.ceil(visible.length / 50));
  const currentPage = Math.min(page, pageCount);
  const offset = (currentPage - 1) * 50;
  return <fieldset disabled={disabled} className="min-w-0 space-y-3 rounded-xl border border-slate-200 bg-white p-3 sm:p-4">
    <legend className="px-1 text-sm font-semibold text-slate-800">Recipients for this send</legend>
    <div className="flex flex-wrap items-center justify-between gap-3"><p aria-live="polite" className="text-sm text-slate-700">{loading ? "Updating audience…" : `${chosen.length} people · ${new Set(chosen.map(row => row.phone_number)).size} WhatsApp messages`}</p><div className="flex gap-3 text-xs font-semibold"><button type="button" className="text-blue-700 hover:underline disabled:opacity-40" disabled={loading || !fresh.length} onClick={() => onChange(fresh.map(row => row.audience_key))}>Select new</button><button type="button" className="text-blue-700 hover:underline disabled:opacity-40" disabled={loading || !eligible.length} onClick={() => onChange(eligible.map(row => row.audience_key))}>Select all</button><button type="button" className="text-slate-600 hover:underline disabled:opacity-40" disabled={!chosen.length} onClick={() => onChange([])}>Clear</button></div></div>
    {previous.length > 0 && <p className="rounded-lg border border-blue-100 bg-blue-50/70 p-3 text-xs leading-5 text-slate-600"><strong className="text-slate-800">{previous.length} earlier update attempts saved.</strong> These people are unchecked by default, including failed attempts. Select all includes earlier recipients; Select new keeps them excluded.</p>}
    <Input type="search" label="Search recipients by name, phone or passport" aria-label="Search update recipients" value={search} onChange={event => { setSearch(event.target.value); setPage(1); }} placeholder="Name, WhatsApp number, passport or imported details" />
    <div role="group" aria-label="Update recipient view" className="flex flex-wrap gap-2">{[["all", `All (${rows.length})`], ["new", `New (${rows.length - previous.length})`], ["previous", `Earlier updates (${previous.length})`]].map(([value, label]) => <button key={value} type="button" aria-pressed={view === value} onClick={() => { setView(value as typeof view); setPage(1); }} className={`rounded-lg border px-2.5 py-1.5 text-xs font-semibold ${view === value ? "border-blue-600 bg-blue-50 text-blue-800" : "border-slate-200 text-slate-500 hover:bg-slate-50"}`}>{label}</button>)}</div>
    <div className="max-h-80 divide-y divide-slate-100 overflow-y-auto rounded-lg border border-slate-200">
      {visible.slice(offset, offset + 50).map(row => <div key={row.audience_key} className={`p-3 transition ${selectedKeys.has(row.audience_key) ? "bg-blue-50/50" : "hover:bg-slate-50/70"}`}>
        <label className="flex cursor-pointer items-start gap-3"><input type="checkbox" aria-label={`Select ${row.name}`} checked={selectedKeys.has(row.audience_key)} disabled={disabled || loading || !row.eligible} onChange={event => { const keys = new Set(selectedKeys); if (event.target.checked) keys.add(row.audience_key); else keys.delete(row.audience_key); onChange([...keys]); }} className="mt-1 h-4 w-4 shrink-0 rounded border-slate-300 accent-blue-600" />
          <span className="min-w-0 flex-1"><span className="flex flex-wrap items-start justify-between gap-2"><span className="break-words text-sm font-semibold text-slate-800">{row.name}</span><span className="flex items-center gap-1.5"><span className="text-[10px] font-medium text-slate-400">Update</span><UpdateStatusBadge status={row.latest_update_status} /></span></span>
            <span className="mt-1 block break-all text-xs tabular-nums text-slate-600">{row.phone_number ?? "No valid WhatsApp number"}{row.passport_number ? ` · Passport ${row.passport_number}` : ""}</span>
            <span className="mt-1 block text-[11px] text-slate-500">{row.phone_source === "submitted" ? "Submitted WhatsApp number · Submitted" : `Imported broadcast number · ${row.submission_status === "needs_review" ? "Match needs review" : "Not submitted"}`}</span>
            <span className="mt-1 block text-[11px] text-slate-500">{documentLabel}: {documentsSent(row) ? "Sent" : row.document_count ? `Pending · ${row.confirmed_count}/${row.document_count} PDFs sent` : "Pending · No PDF assigned"}{row.latest_update_at ? ` · Last update ${formatDateTime(row.latest_update_at)}` : ""}</span>
            {row.reason && <span className="mt-1 block text-xs text-amber-800">{row.reason}</span>}
          </span>
        </label>
        <div className="pl-7"><GroupUpdateRecipientDetails row={row} documentLabel={documentLabel} /></div>
      </div>)}
      {!loading && !visible.length && <p className="p-4 text-sm text-slate-500">No recipients match this view and search.</p>}
    </div>
    {pageCount > 1 && <nav aria-label="Update recipient pages" className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500"><span>{offset + 1}–{Math.min(offset + 50, visible.length)} of {visible.length} · selections include all pages</span><div className="flex items-center gap-3"><button type="button" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)} className="font-semibold text-blue-700 disabled:text-slate-300">Previous</button><span>{currentPage}/{pageCount}</span><button type="button" disabled={currentPage === pageCount} onClick={() => setPage(currentPage + 1)} className="font-semibold text-blue-700 disabled:text-slate-300">Next</button></div></nav>}
    <p className="text-xs leading-5 text-slate-500">Submitted travellers use the WhatsApp number in their completed submission. Others use the imported broadcast number. Shared numbers receive this message once.</p>
  </fieldset>;
}

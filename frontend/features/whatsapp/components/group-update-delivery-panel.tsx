"use client";

import { Download, Search, Send } from "lucide-react";
import { useState } from "react";
import { Button, Input } from "@/components/ui";
import { formatDateTime } from "@/lib/utils/format";
import { distributionDocumentLabel } from "@/features/documents/config/document-distribution-lanes";
import type { WhatsAppBroadcastGroup, WhatsAppLinkedClientGroup } from "../api/whatsapp.api";
import type { GroupUpdateAudience, GroupUpdateRecipient } from "../api/group-updates.api";
import { useGroupUpdateAudience } from "../hooks/use-group-update-audience";
import { documentsSent, UPDATE_ACCEPTED, updateAudienceMatches, updateAudienceSummary, updateStatusLabel } from "../utils/group-update-audience";
import type { WhatsAppRecipientRosterTab } from "../utils/recipient-roster";
import { DeliveryToolbar } from "./whatsapp-delivery-toolbar";
import { BroadcastUpdateDialog } from "./whatsapp-broadcast-update-dialog";
import { GroupUpdateRecipientDetails, UpdateStatusBadge } from "./group-update-recipient-details";
import { GroupUpdateAudienceFields } from "./group-update-audience";

function matches(row: GroupUpdateRecipient, filter: WhatsAppRecipientRosterTab) {
  const status = row.latest_update_status;
  if (filter === "all") return true;
  if (filter === "sent") return Boolean(status && UPDATE_ACCEPTED.has(status));
  if (filter === "not_sent") return !status || status === "not_sent";
  if (filter === "delivery_left") return status === "submitted" || status === "sent";
  if (filter === "failed") return status === "failed";
  if (filter === "needs_review") return status === "delivery_unknown" || (!row.eligible && !status);
  return false;
}

function exportRows(rows: GroupUpdateRecipient[]) {
  const cell = (value: unknown) => { const text = String(value ?? ""); return `"${(/^[=+@-]/u.test(text) ? "'" : "") + text.replaceAll('"', '""')}"`; };
  const data = [["Name", "Current WhatsApp number", "Number source", "Passport", "Submission", "Update status", "Update destination", "Requested at", "Last status update", "Failure reason", "Saved message"], ...rows.map(row => [row.name, row.phone_number, row.phone_source, row.passport_number, row.submission_status, updateStatusLabel(row.latest_update_status), row.latest_update?.phone_number, row.latest_update?.created_at, row.latest_update_at, row.latest_update?.error, row.latest_update?.message])];
  const url = URL.createObjectURL(new Blob(["\uFEFF", data.map(row => row.map(cell).join(",")).join("\r\n")], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a"); link.href = url; link.download = "update-message-delivery.csv"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function GroupUpdateDeliveryPanel({ group, groups, messageTypes, onMessageTypeChange, readOnly }: {
  group: WhatsAppBroadcastGroup; groups: WhatsAppLinkedClientGroup[]; messageTypes: string[]; onMessageTypeChange: (type: string) => void; readOnly: boolean;
}) {
  const [selectedGroupId, setSelectedGroupId] = useState("");
  const [audienceFilters, setAudienceFilters] = useState<GroupUpdateAudience>({ submission_status: "all", document_status: "all", document_type: "visa" });
  const [filter, setFilter] = useState<WhatsAppRecipientRosterTab>("all");
  const [result, setResult] = useState("");
  const [search, setSearch] = useState("");
  const [compose, setCompose] = useState(false);
  const [page, setPage] = useState(1);
  const groupId = groups.find(item => item.id === selectedGroupId)?.id ?? groups[0]?.id;
  const audience = useGroupUpdateAudience(groupId, audienceFilters.document_type);
  const allRows = (audience.data?.recipients ?? []).filter(row => row.broadcast_group_id === group.id);
  const rows = allRows.filter(row => updateAudienceMatches(row, audienceFilters));
  const counts = Object.fromEntries((["all", "sent", "not_sent", "delivery_left", "failed", "needs_review", "rejected", "unidentified", "replaced"] as WhatsAppRecipientRosterTab[]).map(value => [value, rows.filter(row => matches(row, value)).length])) as Record<WhatsAppRecipientRosterTab, number>;
  const query = search.trim().toLocaleLowerCase();
  const visible = rows.filter(row => matches(row, filter) && (!result || (row.latest_update_status ?? "not_sent") === result) && `${row.name} ${row.phone_number ?? ""} ${row.passport_number ?? ""} ${row.email ?? ""} ${Object.values(row.imported_details ?? {}).join(" ")}`.toLocaleLowerCase().includes(query));
  const documentLabel = distributionDocumentLabel(audienceFilters.document_type);
  const pageCount = Math.max(1, Math.ceil(visible.length / 50));
  const currentPage = Math.min(page, pageCount);
  const offset = (currentPage - 1) * 50;
  return <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
    <DeliveryToolbar messageTypes={messageTypes} messageType="document_update" onMessageTypeChange={onMessageTypeChange} filter={filter} onFilterChange={value => { setFilter(value); setResult(""); setPage(1); }} counts={counts} disabled={false} refreshing={audience.isFetching} onRefresh={() => { void audience.refetch(); }} showContactFilters={false}>
      <GroupUpdateAudienceFields mode="review" audience={audienceFilters} rows={allRows} loading={audience.isLoading} disabled={!groupId} onChange={value => { setAudienceFilters(value); setPage(1); }} />
    </DeliveryToolbar>
    {groups.length > 1 && <label className="block text-xs font-semibold text-slate-600">Linked group<select className="ml-3 rounded-lg border border-slate-300 p-2 text-sm" value={groupId} onChange={event => { setSelectedGroupId(event.target.value); setPage(1); }}>{groups.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}
    <div className="flex flex-wrap items-end justify-between gap-3"><div className="min-w-0 flex-1 sm:max-w-xl"><Input type="search" aria-label="Search update delivery" value={search} onChange={event => { setSearch(event.target.value); setPage(1); }} placeholder="Search name, WhatsApp number, passport or imported details" leftAddon={<Search className="h-4 w-4" />} /></div><div className="flex flex-wrap items-end gap-3"><label className="text-xs font-medium text-slate-600">Latest result<select className="ml-2 h-10 rounded-lg border border-slate-300 px-2 text-xs" value={result} onChange={event => { setResult(event.target.value); setPage(1); }}><option value="">Any result</option>{["not_sent", "queued", "processing", "submitted", "sent", "delivered", "read", "failed", "delivery_unknown", "skipped"].map(status => <option key={status} value={status}>{updateStatusLabel(status)} ({rows.filter(row => (row.latest_update_status ?? "not_sent") === status).length})</option>)}</select></label><Button variant="secondary" size="sm" disabled={!visible.length} onClick={() => exportRows(visible)}><Download className="h-4 w-4" />Export CSV</Button>{!readOnly && <Button size="sm" disabled={!groupId} onClick={() => setCompose(true)}><Send className="h-4 w-4" />Send update</Button>}</div></div>
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-slate-50 px-3 py-3 text-xs text-slate-500"><p><strong className="text-slate-700">{visible.length} matching travellers</strong> · {new Set(visible.map(row => row.phone_number).filter(Boolean)).size} WhatsApp numbers · {visible.filter(row => row.latest_update_status).length} with a saved update attempt</p><p>{updateAudienceSummary(audienceFilters, documentLabel)}</p></div>
    {!groupId ? <p className="p-4 text-sm text-slate-600">Link a client group to this broadcast to review traveller updates.</p> : audience.isLoading ? <p role="status" className="p-4 text-sm text-slate-600">Loading update delivery records…</p> : audience.error ? <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">Could not load update delivery. Use Refresh status to try again.</p> : <div role="region" aria-label="Update message delivery" tabIndex={0} className="overflow-x-auto rounded-xl border border-slate-200"><table className="w-full min-w-[900px] text-left text-sm"><caption className="sr-only">Update messages for travellers in this broadcast, including updates sent from document distribution</caption><thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase text-slate-500"><tr><th scope="col" className="px-4 py-3">Recipient</th><th scope="col" className="px-4 py-3">WhatsApp number</th><th scope="col" className="px-4 py-3">Documents</th><th scope="col" className="px-4 py-3">Latest update</th></tr></thead><tbody className="divide-y divide-slate-100">{visible.slice(offset, offset + 50).map(row => <tr key={row.audience_key} className="align-top hover:bg-slate-50/70"><td className="max-w-lg px-4 py-4"><p className="font-semibold text-slate-800">{row.name}</p>{row.passport_number && <p className="mt-1 text-xs text-slate-500">Passport {row.passport_number}</p>}<GroupUpdateRecipientDetails row={row} documentLabel={documentLabel} /></td><td className="px-4 py-4"><p className="whitespace-nowrap text-xs tabular-nums text-slate-700">{row.phone_number ?? "No valid number"}</p><p className="mt-1 text-[11px] text-slate-500">{row.phone_source === "submitted" ? "Submitted WhatsApp number" : "Imported broadcast number"}</p></td><td className="px-4 py-4"><p className="text-xs text-slate-700">{row.submission_status === "submitted" ? "Submitted" : row.submission_status === "not_submitted" ? "Not submitted" : "Match needs review"}</p><p className="mt-1 text-[11px] text-slate-500">{documentLabel}: {documentsSent(row) ? "Sent" : "Pending"}</p></td><td className="px-4 py-4"><UpdateStatusBadge status={row.latest_update_status} />{row.latest_update_at && <p className="mt-2 text-[11px] text-slate-500">{formatDateTime(row.latest_update_at)}</p>}{row.latest_update?.phone_number && row.latest_update.phone_number !== row.phone_number && <p className="mt-1 text-[11px] text-amber-800">Last sent to {row.latest_update.phone_number}</p>}{row.latest_update?.error && <p className="mt-2 max-w-xs text-xs leading-5 text-red-700">{row.latest_update.error}</p>}{row.reason && <p className="mt-2 max-w-xs text-xs leading-5 text-amber-800">{row.reason}</p>}</td></tr>)}</tbody></table>{!visible.length && <p className="p-5 text-sm text-slate-500">No travellers match these filters.</p>}</div>}
    {pageCount > 1 && <nav aria-label="Update delivery pages" className="flex flex-wrap items-center justify-between gap-3 text-xs text-slate-500"><span>{offset + 1}–{Math.min(offset + 50, visible.length)} of {visible.length} travellers</span><div className="flex items-center gap-3"><Button variant="secondary" size="sm" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}>Previous</Button><span>Page {currentPage} of {pageCount}</span><Button variant="secondary" size="sm" disabled={currentPage === pageCount} onClick={() => setPage(currentPage + 1)}>Next</Button></div></nav>}
    <p className="text-xs leading-5 text-slate-500">Update results are separate from PDF delivery. This view includes earlier Inform / update sends and new group updates. Expand a recipient to see the saved message, actual destination, timestamps and failure details.</p>
    {compose && <BroadcastUpdateDialog group={group} onClose={() => { setCompose(false); void audience.refetch(); }} />}
  </section>;
}

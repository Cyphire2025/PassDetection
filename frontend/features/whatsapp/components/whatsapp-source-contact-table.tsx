"use client";

import { useDeferredValue, useMemo, useState } from "react";
import { Button, Input } from "@/components/ui";
import type { WhatsAppSourceContact } from "../api/whatsapp-source-groups.api";

type SourceContactRow = WhatsAppSourceContact & { source_group_id?: string; source_group_name?: string; source_import_only?: boolean };
const PAGE_SIZE = 25;
const ISSUE_LABELS: Record<string, string> = {
  missing_phone: "WhatsApp number missing", invalid_phone: "WhatsApp number invalid",
  unverified_phone: "No verified WhatsApp contact", missing_name: "Name missing", name_too_long: "Name is too long",
  recipient_limit: "Broadcast recipient limit reached",
};

export function SourceContactTable({ contacts, showGroup = false }: { contacts: SourceContactRow[]; showGroup?: boolean }) {
  const [search, setSearch] = useState("");
  const [requestedPage, setPage] = useState(1);
  const query = useDeferredValue(search.trim().toLowerCase());
  const filtered = useMemo(() => contacts.filter((contact) => (
    !query || [contact.name, contact.phone_number, contact.source_group_name ?? ""].some((value) => value.toLowerCase().includes(query))
  )), [contacts, query]);
  const phoneCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const contact of contacts) {
      if (contact.normalized_phone_number && !contact.issue) counts.set(contact.normalized_phone_number, (counts.get(contact.normalized_phone_number) ?? 0) + 1);
    }
    return counts;
  }, [contacts]);
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const page = Math.min(requestedPage, totalPages);
  const start = (page - 1) * PAGE_SIZE;
  const visible = filtered.slice(start, start + PAGE_SIZE);
  return (
    <div className="space-y-3">
      <Input type="search" label="Search travellers" placeholder="Search by name or WhatsApp number" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} />
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">All traveller rows from the source group</caption>
          <thead className="bg-slate-50 text-xs text-slate-500"><tr>
            <th className="px-3 py-2 font-medium" scope="col">Full name</th><th className="px-3 py-2 font-medium" scope="col">WhatsApp number</th>
            {showGroup && <th className="px-3 py-2 font-medium" scope="col">Source group</th>}
            <th className="px-3 py-2 font-medium" scope="col">Contact status</th>
          </tr></thead>
          <tbody className="divide-y divide-slate-100">
            {visible.map((contact) => {
              const shared = Boolean(contact.normalized_phone_number && (phoneCounts.get(contact.normalized_phone_number) ?? 0) > 1);
              return <tr key={`${contact.source_group_id ?? "source"}-${contact.source_submission_id}`}>
                <td className="min-w-28 break-words px-3 py-2 text-slate-800">{contact.name || "Name missing"}</td>
                <td className="min-w-28 break-all px-3 py-2 tabular-nums text-slate-600">{contact.phone_number || "Not provided"}</td>
                {showGroup && <td className="min-w-28 px-3 py-2 text-slate-600">{contact.source_group_name}{contact.source_import_only && <span className="mt-1 block text-xs text-slate-500">Import only</span>}</td>}
                <td className="min-w-32 px-3 py-2 text-xs">{contact.issue
                  ? <span className="text-amber-800">{ISSUE_LABELS[contact.issue] ?? contact.issue}</span>
                  : <span className={shared ? "text-blue-700" : "text-emerald-700"}>{shared ? "Shared number · one message" : "Ready for delivery"}</span>}</td>
              </tr>;
            })}
            {visible.length === 0 && <tr><td colSpan={showGroup ? 4 : 3} className="p-6 text-center text-slate-500">No travellers match this search.</td></tr>}
          </tbody>
        </table>
      </div>
      <nav aria-label="Traveller list pagination" className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
        <span>{filtered.length ? `${start + 1}–${Math.min(start + PAGE_SIZE, filtered.length)} of ${filtered.length.toLocaleString()}` : "0 travellers"}</span>
        {totalPages > 1 && <div className="flex items-center gap-2"><Button type="button" variant="secondary" size="sm" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous</Button><span>Page {page} of {totalPages}</span><Button type="button" variant="secondary" size="sm" disabled={page === totalPages} onClick={() => setPage(page + 1)}>Next</Button></div>}
      </nav>
    </div>
  );
}

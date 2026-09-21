"use client";

import { useDeferredValue, useMemo, useState } from "react";
import { Button, Input } from "@/components/ui";
import type { WhatsAppSourceContact } from "../api/whatsapp-source-groups.api";

type SourceContactRow = WhatsAppSourceContact & { source_group_id?: string; source_group_name?: string; source_import_only?: boolean };
type TravellerFilter = "all" | "ready" | "review" | "shared";
type ContactSet = { key: string; phone: string | null; contacts: SourceContactRow[] };
const PAGE_SIZE = 25;
const FILTER_LABELS: Record<TravellerFilter, string> = { all: "All", ready: "Ready", review: "Needs review", shared: "Shared" };
const ISSUE_LABELS: Record<string, string> = {
  missing_phone: "WhatsApp number missing", invalid_phone: "WhatsApp number invalid",
  unverified_phone: "No verified WhatsApp contact", missing_name: "Name missing", name_too_long: "Name is too long",
  recipient_limit: "Broadcast recipient limit reached",
};

function isContactReady(contact: SourceContactRow) {
  return Boolean(contact.normalized_phone_number && !contact.issue);
}

function matchesSearch(contact: SourceContactRow, query: string) {
  return !query || [contact.name, contact.phone_number, contact.normalized_phone_number ?? "", contact.source_group_name ?? ""]
    .some((value) => value.toLowerCase().includes(query));
}

function paginateContactSets(sets: ContactSet[]) {
  const pages: ContactSet[][] = [[]];
  let currentSize = 0;
  for (const set of sets) {
    if (currentSize > 0 && currentSize + set.contacts.length > PAGE_SIZE) {
      pages.push([]);
      currentSize = 0;
    }
    pages[pages.length - 1].push(set);
    currentSize += set.contacts.length;
  }
  return pages;
}

function TravellerRow({ contact, showGroup, shared, sharedRole }: {
  contact: SourceContactRow;
  showGroup: boolean;
  shared: boolean;
  sharedRole: "primary" | "additional" | null;
}) {
  const issue = contact.issue ?? (!contact.normalized_phone_number ? contact.phone_number ? "invalid_phone" : "missing_phone" : null);
  return <tr className={sharedRole === "primary" ? "bg-blue-50/35" : undefined}>
    <td className="min-w-36 break-words px-3 py-2.5 text-slate-800">
      <span className={sharedRole === "primary" ? "font-semibold" : undefined}>{contact.name || "Name missing"}</span>
      {sharedRole && <span className={`mt-1 block text-[11px] ${sharedRole === "primary" ? "font-medium text-blue-700" : "text-slate-500"}`}>{sharedRole === "primary" ? "Primary contact" : "Shares this number"}</span>}
    </td>
    <td className="min-w-28 break-all px-3 py-2.5 tabular-nums text-slate-600">{contact.phone_number || "Not provided"}</td>
    {showGroup && <td className="min-w-28 px-3 py-2.5 text-slate-600">{contact.source_group_name}{contact.source_import_only && <span className="mt-1 block text-xs text-slate-500">Import only</span>}</td>}
    <td className="min-w-32 px-3 py-2.5 text-xs">{issue
      ? <span className="text-amber-800">{ISSUE_LABELS[issue] ?? issue}</span>
      : <span className={shared ? "text-blue-700" : "text-emerald-700"}>{shared ? "Shared number · one message" : "Ready for delivery"}</span>}</td>
  </tr>;
}

export function SourceContactTable({ contacts, showGroup = false }: { contacts: SourceContactRow[]; showGroup?: boolean }) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<TravellerFilter>("all");
  const [requestedPage, setPage] = useState(1);
  const query = useDeferredValue(search.trim().toLowerCase());
  const phoneGroups = useMemo(() => {
    const groups = new Map<string, SourceContactRow[]>();
    for (const contact of contacts) {
      const phone = contact.normalized_phone_number;
      if (!phone) continue;
      const group = groups.get(phone);
      if (group) group.push(contact);
      else groups.set(phone, [contact]);
    }
    return groups;
  }, [contacts]);
  const counts = useMemo(() => {
    const ready = contacts.filter(isContactReady).length;
    const shared = Array.from(phoneGroups.values()).reduce((count, group) => count + (group.length > 1 ? group.length : 0), 0);
    return { all: contacts.length, ready, review: contacts.length - ready, shared };
  }, [contacts, phoneGroups]);
  const filteredSets = useMemo<ContactSet[]>(() => {
    if (filter === "shared") {
      return Array.from(phoneGroups.entries())
        .filter(([, group]) => group.length > 1 && group.some((contact) => matchesSearch(contact, query)))
        .map(([phone, group]) => ({ key: phone, phone, contacts: group }));
    }
    return contacts.filter((contact) => (
      (filter === "all" || (filter === "ready" ? isContactReady(contact) : !isContactReady(contact)))
      && matchesSearch(contact, query)
    )).map((contact) => ({ key: `${contact.source_group_id ?? "source"}-${contact.source_submission_id}`, phone: null, contacts: [contact] }));
  }, [contacts, filter, phoneGroups, query]);
  const pages = useMemo(() => paginateContactSets(filteredSets), [filteredSets]);
  const totalPages = pages.length;
  const page = Math.min(requestedPage, totalPages);
  const visibleSets = pages[page - 1];
  const filteredCount = filteredSets.reduce((count, set) => count + set.contacts.length, 0);
  const start = pages.slice(0, page - 1).reduce((count, sets) => count + sets.reduce((size, set) => size + set.contacts.length, 0), 0);
  const visibleCount = visibleSets.reduce((count, set) => count + set.contacts.length, 0);
  return (
    <div className="space-y-3">
      <div role="group" aria-label="Filter travellers" className="flex flex-wrap gap-2">
        {(Object.keys(FILTER_LABELS) as TravellerFilter[]).map((value) => <button key={value} type="button" aria-pressed={filter === value} aria-label={`${FILTER_LABELS[value]}: ${counts[value].toLocaleString()} travellers`} onClick={() => { setFilter(value); setPage(1); }} className={`inline-flex min-h-9 items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 ${filter === value ? "border-blue-200 bg-blue-50 text-blue-800" : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50"}`}>
          {FILTER_LABELS[value]}<span className={`rounded px-1.5 py-0.5 tabular-nums ${filter === value ? "bg-blue-100 text-blue-800" : "bg-slate-100 text-slate-500"}`}>{counts[value].toLocaleString()}</span>
        </button>)}
      </div>
      <Input type="search" label="Search travellers" placeholder="Search by name or WhatsApp number" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} />
      {filter === "shared" && <p className="text-xs leading-5 text-slate-500">The primary contact is the first traveller listed for each number in the source data. Searches show the whole shared group.</p>}
      <div className="overflow-x-auto rounded-lg border border-slate-200" aria-busy={query !== search.trim().toLowerCase()}>
        <table className="w-full text-left text-sm">
          <caption className="sr-only">{FILTER_LABELS[filter]} traveller rows from the source group</caption>
          <thead className="bg-slate-50 text-xs text-slate-500"><tr>
            <th className="px-3 py-2 font-medium" scope="col">Full name</th><th className="px-3 py-2 font-medium" scope="col">WhatsApp number</th>
            {showGroup && <th className="px-3 py-2 font-medium" scope="col">Source group</th>}
            <th className="px-3 py-2 font-medium" scope="col">Contact status</th>
          </tr></thead>
          {visibleSets.map((set) => <tbody key={set.key} className="divide-y divide-slate-100 border-b border-slate-100 last:border-b-0">
            {filter === "shared" && <tr className="bg-slate-50"><th scope="rowgroup" colSpan={showGroup ? 4 : 3} className="px-3 py-2.5 text-left text-xs font-medium text-slate-600"><span className="tabular-nums text-slate-800">{set.phone}</span><span className="ml-2 font-normal">{set.contacts.length.toLocaleString()} travellers share this number</span></th></tr>}
            {set.contacts.map((contact, index) => <TravellerRow key={`${contact.source_group_id ?? "source"}-${contact.source_submission_id}`} contact={contact} showGroup={showGroup} shared={Boolean(contact.normalized_phone_number && (phoneGroups.get(contact.normalized_phone_number)?.length ?? 0) > 1)} sharedRole={filter === "shared" ? index === 0 ? "primary" : "additional" : null} />)}
          </tbody>)}
          {visibleCount === 0 && <tbody><tr><td colSpan={showGroup ? 4 : 3} className="p-6 text-center text-slate-500">{query ? "No travellers match this search and filter." : filter === "shared" ? "No travellers share a WhatsApp number." : filter === "review" ? "No traveller contact details need review." : "No travellers in this filter."}</td></tr></tbody>}
        </table>
      </div>
      <nav aria-label="Traveller list pagination" className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
        <span role="status" aria-live="polite">{filteredCount ? `${(start + 1).toLocaleString()}–${(start + visibleCount).toLocaleString()} of ${filteredCount.toLocaleString()} travellers` : "0 travellers"}{filter === "shared" && filteredSets.length > 0 ? ` · ${filteredSets.length.toLocaleString()} shared ${filteredSets.length === 1 ? "number" : "numbers"}` : ""}</span>
        {totalPages > 1 && <div className="flex items-center gap-2"><Button type="button" variant="secondary" size="sm" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous</Button><span>Page {page} of {totalPages}</span><Button type="button" variant="secondary" size="sm" disabled={page === totalPages} onClick={() => setPage(page + 1)}>Next</Button></div>}
      </nav>
      {filter === "shared" && totalPages > 1 && <p className="text-xs text-slate-400">Shared-number groups stay together on each page.</p>}
    </div>
  );
}

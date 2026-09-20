"use client";

import { Archive, ChevronDown, Users } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Button, Skeleton } from "@/components/ui";
import { WorkspaceEmptyState } from "@/components/shared/workspace-ui";
import { formatDateTime } from "@/lib/utils/format";
import type { WhatsAppBroadcastGroup } from "../api/whatsapp.api";

const PAGE_SIZE = 20;

export function WhatsAppBroadcastList({
  groups, totalCount, archived = false, expanded = false, onToggle, isLoading, renderActions, onCreate,
}: {
  groups: WhatsAppBroadcastGroup[];
  totalCount: number;
  archived?: boolean;
  expanded?: boolean;
  onToggle?: () => void;
  isLoading: boolean;
  renderActions: (group: WhatsAppBroadcastGroup, surface: "mobile" | "desktop") => ReactNode;
  onCreate: () => void;
}) {
  const [page, setPage] = useState(1);
  const pageCount = Math.max(1, Math.ceil(groups.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const offset = (currentPage - 1) * PAGE_SIZE;
  const visibleGroups = groups.slice(offset, offset + PAGE_SIZE);
  const headingId = archived ? "whatsapp-archived-groups-heading" : "whatsapp-broadcast-groups-heading";
  const title = archived ? "Archived broadcasts" : "Active broadcasts";
  const contentId = `${headingId}-content`;
  const isExpanded = !archived || expanded;

  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm" aria-labelledby={headingId}>
      {archived ? (
        <div className={isExpanded ? "border-b border-slate-200" : undefined}>
          <h2 id={headingId}>
            <button
              type="button"
              aria-expanded={isExpanded}
              aria-controls={contentId}
              aria-label={title}
              onClick={onToggle}
              className="flex w-full items-center justify-between gap-3 px-4 py-3.5 text-left hover:bg-slate-50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-emerald-600 sm:px-5"
            >
              <span className="flex items-center gap-2 font-semibold text-slate-950"><Archive aria-hidden="true" className="h-4 w-4 text-slate-500" />{title}</span>
              <span className="flex items-center gap-3">
                <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">{totalCount.toLocaleString()}</span>
                <ChevronDown aria-hidden="true" className={`h-4 w-4 text-slate-500 transition-transform motion-reduce:transition-none ${isExpanded ? "rotate-180" : ""}`} />
              </span>
            </button>
          </h2>
          {isExpanded && <p className="px-4 pb-3.5 text-sm text-slate-500 sm:px-5">Recipient lists and delivery history are retained. Restore a broadcast to use it again.</p>}
        </div>
      ) : <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3.5 sm:px-5">
        <div>
          <h2 id={headingId} className="font-semibold text-slate-950">{title}</h2>
          <p className="mt-1 text-sm text-slate-500">
            Manage recipients and send approved trip messages.
          </p>
        </div>
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">{totalCount.toLocaleString()}</span>
      </div>}
      <div id={contentId} hidden={!isExpanded}>
      {isExpanded && (isLoading ? (
        <div className="space-y-3 p-5">{Array.from({ length: 3 }, (_, index) => <Skeleton key={index} className="h-16 w-full rounded-lg" />)}</div>
      ) : totalCount === 0 ? (
        <WorkspaceEmptyState
          title={archived ? "No archived broadcasts" : "No active broadcasts"}
          description={archived ? "Archived broadcasts will appear here with their recipients and delivery history." : "Create a broadcast or restore one from the archive below."}
          action={archived ? undefined : <Button type="button" onClick={onCreate}>Create Broadcast</Button>}
        />
      ) : groups.length === 0 ? (
        <WorkspaceEmptyState filtered title={`No ${archived ? "archived" : "active"} broadcasts match this search`} description="Search by the broadcast name or clear the shared search to see every broadcast." />
      ) : (
        <>
          <div className="divide-y divide-slate-100 md:hidden">
            {visibleGroups.map((group) => (
              <article key={group.id} className="px-4 py-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="font-semibold text-slate-950">{group.name}</h3>
                    {group.has_import_only_source && <ImportOnlySourceBadge />}
                    <p className="mt-1 text-xs text-slate-500">{archived ? "Archived" : "Updated"} {formatDateTime(archived ? group.archived_at ?? group.updated_at : group.updated_at)}</p>
                  </div>
                  {renderActions(group, "mobile")}
                </div>
                <p className="mt-3 text-sm text-slate-700">{(group.source_contact_count ?? 0) > 0 ? `${group.source_contact_count!.toLocaleString()} travellers` : `${group.total_contact_count.toLocaleString()} total contacts`}</p>
                <p className="mt-1 text-xs text-slate-500">{archived ? "Read-only · restore to edit or send messages" : `${group.recipient_count.toLocaleString()} ${(group.source_contact_count ?? 0) > 0 ? "delivery numbers" : "eligible to receive"}`}</p>
                {!archived && !group.source_contact_count && group.total_contact_count !== group.recipient_count && <p className="mt-2 text-xs text-amber-700">{(group.total_contact_count - group.recipient_count).toLocaleString()} contact exceptions require review</p>}
              </article>
            ))}
          </div>
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full min-w-[760px] text-left text-sm">
              <caption className="sr-only">{title} and recipient history</caption>
              <thead className="border-b border-slate-200 bg-slate-50 font-medium text-slate-600">
                <tr>
                  <th scope="col" className="px-5 py-3.5">Group Name</th>
                  <th scope="col" className="px-5 py-3.5">{archived ? "Retained contacts" : "Recipient readiness"}</th>
                  <th scope="col" className="px-5 py-3.5">{archived ? "Archived" : "Updated"}</th>
                  <th scope="col" className="px-5 py-3.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {visibleGroups.map((group) => (
                  <tr key={group.id} className="transition-colors hover:bg-slate-50/70">
                    <td className="px-5 py-4">
                      <div className="font-medium text-slate-900">{group.name}</div>
                      {group.has_import_only_source && <ImportOnlySourceBadge />}
                      <div className="mt-1 text-xs text-slate-500">{archived ? <span className="inline-flex items-center gap-1"><Archive className="h-3 w-3" />Archived · read-only</span> : "Used in approved trip wording"}</div>
                    </td>
                    <td className="px-5 py-4 text-slate-700">
                      <span className="inline-flex items-center gap-1.5 font-medium"><Users className="h-4 w-4 text-slate-400" />{(group.source_contact_count ?? 0) > 0 ? `${group.source_contact_count!.toLocaleString()} travellers` : `${group.total_contact_count.toLocaleString()} total contacts`}</span>
                      {archived ? <p className="mt-1 text-xs text-slate-500">Delivery history retained</p> : <>
                        <p className="mt-1 text-xs text-emerald-700">{group.recipient_count.toLocaleString()} {(group.source_contact_count ?? 0) > 0 ? "delivery numbers" : "eligible to receive"}</p>
                        {!group.source_contact_count && group.total_contact_count !== group.recipient_count && <p className="mt-1 text-xs text-amber-700">{(group.total_contact_count - group.recipient_count).toLocaleString()} contact exceptions</p>}
                      </>}
                    </td>
                    <td className="px-5 py-4 text-slate-600">{formatDateTime(archived ? group.archived_at ?? group.updated_at : group.updated_at)}</td>
                    <td className="px-5 py-4"><div className="flex justify-end">{renderActions(group, "desktop")}</div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {pageCount > 1 && (
            <nav aria-label={`${title} pagination`} className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-4 py-3 text-sm">
              <span className="text-slate-500" aria-live="polite">{offset + 1}–{Math.min(offset + PAGE_SIZE, groups.length)} of {groups.length.toLocaleString()}</span>
              <div className="flex items-center gap-3">
                <Button type="button" size="sm" variant="secondary" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}>Previous</Button>
                <span>Page {currentPage} of {pageCount}</span>
                <Button type="button" size="sm" variant="secondary" disabled={currentPage === pageCount} onClick={() => setPage(currentPage + 1)}>Next</Button>
              </div>
            </nav>
          )}
        </>
      ))}
      </div>
    </section>
  );
}

function ImportOnlySourceBadge() {
  return <span className="mt-1.5 inline-flex rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">Import only</span>;
}

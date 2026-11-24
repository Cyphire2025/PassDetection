"use client";

import { Bot, ClipboardList, Clock3, UsersRound } from "lucide-react";
import { Button, Skeleton } from "@/components/ui";
import { WorkspaceEmptyState, WorkspaceErrorNotice, WorkspacePageHeader, WorkspaceSummaryItem, WorkspaceSummaryStrip } from "@/components/shared/workspace-ui";
import { formatCompactTime, toLabel } from "../audit-filter-model";
import { useAuditLedger } from "../hooks/use-audit-ledger";
import { AuditFilterControls } from "./audit-filter-controls";
import { AuditLedgerRows } from "./audit-ledger-rows";

export function AuditLedgerPage() {
  const controller = useAuditLedger();
  const { role, auditQuery, exportNotice, data, actors, systemEvents, latestEvent,
    isFiltered, hasMore, isIncomplete, hasBrokenContinuation } = controller;
  return (
    <div className="flex flex-col gap-5">
      <WorkspacePageHeader
        title="Audit Logs"
        description="Review account activity and security events."
        icon={ClipboardList}
        accent="lime"
      />

      {auditQuery.error && (
        <WorkspaceErrorNotice>
          Audit logs could not be loaded. Please try again.
        </WorkspaceErrorNotice>
      )}

      {exportNotice && (
        <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-950" role="status">
          {exportNotice}
        </div>
      )}

      <WorkspaceSummaryStrip label="Loaded audit events">
        {auditQuery.isLoading ? (
          Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-[72px] rounded-none" />
          ))
        ) : (
          <>
            <WorkspaceSummaryItem
              label="Loaded events"
              value={data.length.toLocaleString()}
              helper={isIncomplete ? "more history available" : "all matching events loaded"}
              icon={ClipboardList}
              tone="info"
            />
            <WorkspaceSummaryItem
              label="Users"
              value={actors.size.toLocaleString()}
              helper="in loaded events"
              icon={UsersRound}
            />
            <WorkspaceSummaryItem
              label="System events"
              value={systemEvents.toLocaleString()}
              helper="in loaded events"
              icon={Bot}
            />
            <WorkspaceSummaryItem
              label="Latest loaded"
              value={latestEvent ? formatCompactTime(latestEvent.created_at) : "No events"}
              helper={latestEvent ? toLabel(latestEvent.event_type) : undefined}
              icon={Clock3}
              tone="success"
            />
          </>
        )}
      </WorkspaceSummaryStrip>

      <AuditFilterControls controller={controller} />

      <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm" aria-labelledby="audit-ledger-heading">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 px-4 py-3.5 sm:px-5">
          <div>
            <h2 id="audit-ledger-heading" className="mt-0.5 font-semibold text-slate-950">Activity history</h2>
          </div>
          <p className="text-sm text-slate-600" aria-live="polite">
            {auditQuery.isFetching && !auditQuery.isFetchingNextPage
              ? "Refreshing events…"
              : isIncomplete
                ? `${data.length.toLocaleString()} loaded · more available`
                : `${data.length.toLocaleString()} loaded · all matching events loaded`}
          </p>
        </div>

        {auditQuery.isLoading ? (
          <div className="grid gap-3 p-4 sm:p-5">
            {Array.from({ length: 7 }).map((_, index) => (
              <Skeleton key={index} className="h-16 w-full rounded-lg" />
            ))}
          </div>
        ) : auditQuery.error ? (
          <WorkspaceEmptyState
            title="Audit events could not be loaded"
            description="Check your session and agency filter, then try again."
          />
        ) : data.length === 0 ? (
          <WorkspaceEmptyState
            filtered={isFiltered}
            title={isFiltered ? "No events match these filters" : "No audit events have been recorded"}
            description={isFiltered
              ? "Clear or broaden a filter to view more events."
              : "Account activity and security events will appear here."}
          />
        ) : (
          <>
            <AuditLedgerRows data={data} showAgency={role === "super_admin"} />
            <div className="border-t border-slate-200 p-4 text-center">
              {hasMore ? (
                <Button type="button" variant="secondary" onClick={() => { void auditQuery.fetchNextPage(); }} isLoading={auditQuery.isFetchingNextPage}>
                  Load older events
                </Button>
              ) : hasBrokenContinuation ? (
                <p role="alert" className="text-sm font-medium text-amber-800">
                  Some events could not be loaded. Refresh or narrow the filters before using these results as a complete record.
                </p>
              ) : isIncomplete ? (
                <p role="status" className="text-sm font-medium text-amber-800">
                  More events are available. Load older events to complete these results.
                </p>
              ) : (
                <p className="text-sm text-slate-500">All matching events have been loaded.</p>
              )}
            </div>
          </>
        )}
      </section>
    </div>
  );
}


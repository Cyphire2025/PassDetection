"use client";

import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  Bot,
  ClipboardList,
  Clock3,
  Download,
  FilterX,
  ShieldCheck,
  UserRound,
  UsersRound,
} from "lucide-react";
import {
  WorkspaceEmptyState,
  WorkspaceErrorNotice,
  WorkspacePageHeader,
  WorkspaceSummaryItem,
  WorkspaceSummaryStrip,
} from "@/components/shared/workspace-ui";
import { Badge, Button, Input, Skeleton } from "@/components/ui";
import { formatDateTime } from "@/lib/utils/format";
import { selectUserRole, useAuthStore } from "@/stores/auth.store";
import type {
  AuditLogFilters,
  AuditLogListItem,
  AuditLogResult,
} from "@/features/operations/api/operations.api";
import {
  useAuditLogExport,
  useAuditLogPages,
} from "@/features/operations/hooks/use-operations";

interface AuditFilterState {
  startAt: string;
  endAt: string;
  actor: string;
  eventType: string;
  entityType: string;
  entityId: string;
  result: "" | AuditLogResult;
  agencyId: string;
}

const EMPTY_FILTERS: AuditFilterState = {
  startAt: "",
  endAt: "",
  actor: "",
  eventType: "",
  entityType: "",
  entityId: "",
  result: "",
  agencyId: "",
};

export default function AuditLogsPage() {
  const role = useAuthStore(selectUserRole);
  const sessionVersion = useAuthStore((state) => state.sessionVersion);
  const [filters, setFilters] = useState<AuditFilterState>(EMPTY_FILTERS);
  const deferredFilters = useDeferredValue(filters);
  const apiFilters = useMemo(
    () => toApiFilters(deferredFilters, role === "super_admin"),
    [deferredFilters, role],
  );
  const auditQuery = useAuditLogPages(apiFilters);
  const exportMutation = useAuditLogExport();
  const exportControllerRef = useRef<AbortController | null>(null);
  const [exportNotice, setExportNotice] = useState<string | null>(null);
  const auditPages = auditQuery.data?.pages;
  const data = useMemo(() => {
    const byId = new Map<string, AuditLogListItem>();
    for (const page of auditPages ?? []) {
      for (const item of page.items) byId.set(item.id, item);
    }
    return Array.from(byId.values());
  }, [auditPages]);
  const actors = useMemo(
    () => new Set(data.flatMap((log) => (log.actor_email ? [log.actor_email] : []))),
    [data],
  );
  const systemEvents = useMemo(
    () => data.filter((log) => !log.actor_email).length,
    [data],
  );
  const latestEvent = data[0] ?? null;
  const isFiltered = Object.values(filters).some(Boolean);
  const hasMore = auditQuery.hasNextPage === true;
  const latestPage = auditPages && auditPages.length > 0
    ? auditPages[auditPages.length - 1]
    : null;
  const isIncomplete = latestPage?.incomplete === true;
  const hasBrokenContinuation = isIncomplete && latestPage?.has_more === true && !latestPage.next_cursor;
  const canExport = Boolean(apiFilters.start_at && apiFilters.end_at);

  useEffect(() => () => {
    exportControllerRef.current?.abort();
    exportControllerRef.current = null;
  }, [sessionVersion]);

  const updateFilter = <Field extends keyof AuditFilterState>(
    field: Field,
    value: AuditFilterState[Field],
  ) => {
    setFilters((current) => ({ ...current, [field]: value }));
  };

  const exportLedger = async () => {
    const startAt = apiFilters.start_at;
    const endAt = apiFilters.end_at;
    if (!startAt || !endAt || exportMutation.isPending) return;
    setExportNotice(null);
    exportControllerRef.current?.abort();
    const controller = new AbortController();
    exportControllerRef.current = controller;
    try {
      const exported = await exportMutation.mutateAsync({
        filters: {
          ...apiFilters,
          start_at: startAt,
          end_at: endAt,
        },
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(exported.content);
      const link = document.createElement("a");
      link.href = url;
      link.download = `audit-logs-${new Date().toISOString().slice(0, 10)}.csv`;
      link.click();
      URL.revokeObjectURL(url);
      setExportNotice(exported.truncated
        ? "The export reached the 10,000-row safety limit. Narrow the time range for complete evidence."
        : "The audit export is ready.");
    } catch {
      if (controller.signal.aborted) return;
      setExportNotice("The audit export could not be prepared. Please try again.");
    } finally {
      if (exportControllerRef.current === controller) {
        exportControllerRef.current = null;
      }
    }
  };

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

      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5" aria-labelledby="audit-filter-heading">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 id="audit-filter-heading" className="mt-0.5 font-semibold text-slate-950">Filters</h2>
            <p className="mt-1 text-sm text-slate-600">Filter events by date, user, action, or result.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="secondary" onClick={() => setFilters(EMPTY_FILTERS)} disabled={!isFiltered}>
              <FilterX className="h-4 w-4" aria-hidden="true" /> Clear filters
            </Button>
            <Button type="button" onClick={() => { void exportLedger(); }} disabled={!canExport} isLoading={exportMutation.isPending}>
              <Download className="h-4 w-4" aria-hidden="true" /> Export CSV
            </Button>
          </div>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <Input id="audit-start-at" type="datetime-local" label="Start time" value={filters.startAt} onChange={(event) => updateFilter("startAt", event.target.value)} />
          <Input id="audit-end-at" type="datetime-local" label="End time" value={filters.endAt} onChange={(event) => updateFilter("endAt", event.target.value)} />
          <Input id="audit-actor" label="Actor email or user ID" value={filters.actor} onChange={(event) => updateFilter("actor", event.target.value)} maxLength={255} autoComplete="off" />
          <Input id="audit-event-type" label="Event type" value={filters.eventType} onChange={(event) => updateFilter("eventType", event.target.value)} maxLength={80} autoComplete="off" placeholder="passport.deleted" />
          <Input id="audit-entity-type" label="Entity type" value={filters.entityType} onChange={(event) => updateFilter("entityType", event.target.value)} maxLength={80} autoComplete="off" />
          <Input id="audit-entity-id" label="Entity identifier" value={filters.entityId} onChange={(event) => updateFilter("entityId", event.target.value)} maxLength={128} autoComplete="off" />
          <label className="flex flex-col gap-1.5 text-sm font-medium text-slate-700" htmlFor="audit-result">
            Result
            <select id="audit-result" value={filters.result} onChange={(event) => updateFilter("result", auditResultFilter(event.target.value))} className="h-9 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 focus:border-transparent focus:outline-none focus:ring-2 focus:ring-blue-600">
              <option value="">All results</option>
              <option value="success">Success</option>
              <option value="blocked">Blocked</option>
              <option value="denied">Denied</option>
              <option value="failed">Failed</option>
            </select>
          </label>
          {role === "super_admin" && (
            <Input id="audit-agency-id" label="Agency ID" value={filters.agencyId} onChange={(event) => updateFilter("agencyId", event.target.value)} maxLength={36} autoComplete="off" placeholder="Optional agency ID" />
          )}
        </div>
        <p className="mt-3 text-xs text-slate-500">CSV export requires both times and is limited to 31 days and 10,000 rows per request.</p>
      </section>

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
            <div className="grid min-w-0 grid-cols-1 gap-3 p-4 md:hidden">
              {data.map((log) => (
                <article key={log.id} className="min-w-0 rounded-xl border border-slate-200 bg-white p-4" style={{ contentVisibility: "auto", containIntrinsicSize: "0 160px" }}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold text-slate-950">{toLabel(log.event_type)}</p>
                      <p className="mt-1 flex min-w-0 items-center gap-1.5 text-sm text-slate-600">
                        {log.actor_email ? <UserRound className="h-3.5 w-3.5 shrink-0" aria-hidden="true" /> : <Bot className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />}
                        <span className="min-w-0 truncate" title={log.actor_email ?? "System"}>{log.actor_email ?? "System"}</span>
                      </p>
                    </div>
                    <ActivityMark action={log.event_type} />
                  </div>
                  <dl className="mt-3 grid grid-cols-2 gap-3 border-t border-slate-100 pt-3 text-sm">
                    <div><dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Entity</dt><dd className="mt-1 break-all text-slate-800">{toLabel(log.entity_type)} {log.entity_id ? `#${log.entity_id}` : ""}</dd></div>
                    <div><dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Result</dt><dd className="mt-1"><ResultBadge result={log.result} /></dd></div>
                    {role === "super_admin" ? <div className="col-span-2"><dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Tenant</dt><dd className="mt-1 break-all text-slate-800">{log.agency_id ?? "Global scope"}</dd></div> : null}
                    <div className="col-span-2"><dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Recorded</dt><dd className="mt-1 text-slate-800">{formatDateTime(log.created_at)}</dd></div>
                  </dl>
                </article>
              ))}
            </div>

            <div className="hidden overflow-x-auto md:block">
              <table className="w-full min-w-[900px] text-left text-sm">
                <caption className="sr-only">Audit log events</caption>
                <thead><tr className="border-b border-slate-200 bg-slate-50/70 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500"><th scope="col" className="px-5 py-3">Event</th><th scope="col" className="px-5 py-3">Actor</th><th scope="col" className="px-5 py-3">Entity</th>{role === "super_admin" ? <th scope="col" className="px-5 py-3">Tenant</th> : null}<th scope="col" className="px-5 py-3">Result</th><th scope="col" className="px-5 py-3">Recorded</th></tr></thead>
                <tbody className="divide-y divide-slate-100">
                  {data.map((log) => (
                    <tr key={log.id} className="transition-colors hover:bg-slate-50/70">
                      <td className="px-5 py-4"><div className="flex items-center gap-3"><ActivityMark action={log.event_type} /><span className="font-medium text-slate-950">{toLabel(log.event_type)}</span></div></td>
                      <td className="px-5 py-4 text-slate-700"><span className="flex items-center gap-2">{log.actor_email ? <UserRound className="h-4 w-4 text-slate-400" aria-hidden="true" /> : <Bot className="h-4 w-4 text-slate-400" aria-hidden="true" />}{log.actor_email ?? "System"}</span></td>
                      <td className="max-w-64 break-all px-5 py-4 text-slate-700">{toLabel(log.entity_type)} {log.entity_id ? `#${log.entity_id}` : ""}</td>
                      {role === "super_admin" ? <td className="max-w-64 break-all px-5 py-4 text-slate-700">{log.agency_id ?? "Global scope"}</td> : null}
                      <td className="px-5 py-4"><ResultBadge result={log.result} /></td>
                      <td className="px-5 py-4 text-slate-600">{formatDateTime(log.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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

function ResultBadge({ result }: { result: AuditLogResult | null }) {
  const variant = result === "success" ? "success" : result === "blocked" || result === "denied" ? "warning" : result === "failed" ? "destructive" : "outline";
  return <Badge variant={variant}>{result ? toLabel(result) : "Unclassified"}</Badge>;
}

function ActivityMark({ action }: { action: string }) {
  const destructive = /delete|remove|purge|revoke/i.test(action);
  const positive = /create|confirm|approve|restore|save/i.test(action);
  return (
    <span className={destructive ? "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-red-50 text-red-700" : positive ? "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-700" : "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-700"}>
      {destructive ? <ShieldCheck className="h-4 w-4" aria-hidden="true" /> : <Activity className="h-4 w-4" aria-hidden="true" />}
    </span>
  );
}

function toApiFilters(filters: AuditFilterState, includeAgency: boolean): AuditLogFilters {
  const startAt = toIso(filters.startAt);
  const endAt = toIso(filters.endAt);
  const actor = normalized(filters.actor);
  const eventType = normalized(filters.eventType);
  const entityType = normalized(filters.entityType);
  const entityId = normalized(filters.entityId);
  const result = filters.result || null;
  const agencyId = normalized(filters.agencyId);
  return {
    ...(startAt ? { start_at: startAt } : {}),
    ...(endAt ? { end_at: endAt } : {}),
    ...(actor ? { actor } : {}),
    ...(eventType ? { event_type: eventType } : {}),
    ...(entityType ? { entity_type: entityType } : {}),
    ...(entityId ? { entity_id: entityId } : {}),
    ...(result ? { result } : {}),
    ...(includeAgency && agencyId ? { agency_id: agencyId } : {}),
  };
}

function toIso(value: string) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function normalized(value: string) {
  return value.trim().replace(/\s+/g, " ");
}

function auditResultFilter(value: string): AuditFilterState["result"] {
  return value === "success"
    || value === "blocked"
    || value === "denied"
    || value === "failed"
    ? value
    : "";
}

function formatCompactTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Recorded";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function toLabel(value: string) {
  return value.replace(/[_.]/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

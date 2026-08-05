"use client";

import { useDeferredValue, useMemo, useState } from "react";
import {
  Activity,
  Bot,
  ClipboardList,
  Clock3,
  ShieldCheck,
  UserRound,
  UsersRound,
} from "lucide-react";
import {
  WorkspaceEmptyState,
  WorkspaceErrorNotice,
  WorkspaceHeaderContext,
  WorkspacePageHeader,
  WorkspaceSummaryItem,
  WorkspaceSummaryStrip,
  WorkspaceToolbar,
} from "@/components/shared/workspace-ui";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDateTime } from "@/lib/utils/format";
import { useAuditLogs } from "@/features/operations/hooks/use-operations";

export default function AuditLogsPage() {
  const { data = [], isLoading, error } = useAuditLogs();
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);

  const actors = useMemo(
    () => new Set(data.flatMap((log) => (log.actor_email ? [log.actor_email] : []))),
    [data],
  );
  const systemEvents = useMemo(
    () => data.filter((log) => !log.actor_email).length,
    [data],
  );
  const filteredLogs = useMemo(() => {
    const normalized = deferredQuery.trim().toLocaleLowerCase();
    if (!normalized) return data;
    return data.filter((log) =>
      [
        log.action,
        log.actor_email ?? "system",
        log.entity_type,
        log.entity_id ?? "",
      ]
        .join(" ")
        .toLocaleLowerCase()
        .includes(normalized),
    );
  }, [data, deferredQuery]);
  const latestEvent = useMemo(
    () => data.reduce<(typeof data)[number] | null>((latest, log) => {
      if (!latest) return log;
      return Date.parse(log.created_at) > Date.parse(latest.created_at) ? log : latest;
    }, null),
    [data],
  );

  return (
    <div className="flex flex-col gap-5">
      <WorkspacePageHeader
        eyebrow="Accountability ledger"
        title="Audit Logs"
        description="Trace security-sensitive and operational activity across the exact account scope you are permitted to review."
        icon={ClipboardList}
        accent="lime"
        context={(
          <>
            <WorkspaceHeaderContext icon={ShieldCheck}>Permission-scoped ledger</WorkspaceHeaderContext>
            <WorkspaceHeaderContext icon={Activity}>Operational and security events</WorkspaceHeaderContext>
          </>
        )}
      />

      {error && (
        <WorkspaceErrorNotice>
          Audit Logs are unavailable for this account. No history has been removed or changed.
        </WorkspaceErrorNotice>
      )}

      <WorkspaceSummaryStrip label="Audit log summary">
        {isLoading ? (
          Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-[72px] rounded-none" />
          ))
        ) : (
          <>
            <WorkspaceSummaryItem
              label="Recorded events"
              value={data.length.toLocaleString()}
              helper="current scope"
              icon={ClipboardList}
              tone="info"
            />
            <WorkspaceSummaryItem
              label="Human actors"
              value={actors.size.toLocaleString()}
              helper="unique accounts"
              icon={UsersRound}
            />
            <WorkspaceSummaryItem
              label="System events"
              value={systemEvents.toLocaleString()}
              helper="automated actions"
              icon={Bot}
            />
            <WorkspaceSummaryItem
              label="Latest activity"
              value={latestEvent ? formatCompactTime(latestEvent.created_at) : "No events"}
              helper={latestEvent ? toLabel(latestEvent.action) : undefined}
              icon={Clock3}
              tone="success"
            />
          </>
        )}
      </WorkspaceSummaryStrip>

      <section
        className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
        aria-labelledby="audit-ledger-heading"
      >
        <div className="border-b border-slate-200 px-4 py-3.5 sm:px-5">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
            Chronological evidence
          </p>
          <h2 id="audit-ledger-heading" className="mt-0.5 font-semibold text-slate-950">
            Activity ledger
          </h2>
        </div>

        <WorkspaceToolbar
          query={query}
          onQueryChange={setQuery}
          searchLabel="Search audit events"
          placeholder="Search action, actor, entity, or ID"
          resultLabel={`${filteredLogs.length.toLocaleString()} events`}
        />

        {isLoading ? (
          <div className="grid gap-3 p-4 sm:p-5">
            {Array.from({ length: 7 }).map((_, index) => (
              <Skeleton key={index} className="h-16 w-full rounded-lg" />
            ))}
          </div>
        ) : data.length === 0 ? (
          <WorkspaceEmptyState
            title="No audit events have been recorded"
            description="Security and operational activity will appear here as authorised users work across the platform."
          />
        ) : filteredLogs.length === 0 ? (
          <WorkspaceEmptyState
            filtered
            title="No events match this audit search"
            description="Search by the recorded action, actor email, entity type, or the visible entity identifier."
          />
        ) : (
          <>
            <div className="grid gap-3 p-4 md:hidden">
              {filteredLogs.map((log) => (
                <article
                  key={log.id}
                  className="rounded-xl border border-slate-200 bg-white p-4"
                  style={{ contentVisibility: "auto", containIntrinsicSize: "0 160px" }}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-semibold text-slate-950">{toLabel(log.action)}</p>
                      <p className="mt-1 flex items-center gap-1.5 truncate text-sm text-slate-600">
                        {log.actor_email ? (
                          <UserRound className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                        ) : (
                          <Bot className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                        )}
                        {log.actor_email ?? "System"}
                      </p>
                    </div>
                    <ActivityMark action={log.action} />
                  </div>
                  <dl className="mt-3 grid grid-cols-2 gap-3 border-t border-slate-100 pt-3 text-sm">
                    <div>
                      <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Entity</dt>
                      <dd className="mt-1 text-slate-800">
                        {toLabel(log.entity_type)} {log.entity_id ? `#${log.entity_id.slice(0, 8)}` : ""}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Recorded</dt>
                      <dd className="mt-1 text-slate-800">{formatDateTime(log.created_at)}</dd>
                    </div>
                  </dl>
                </article>
              ))}
            </div>

            <div className="hidden overflow-x-auto md:block">
              <table className="w-full min-w-[780px] text-left text-sm">
                <caption className="sr-only">Audit log events</caption>
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50/70 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">
                    <th scope="col" className="px-5 py-3">Event</th>
                    <th scope="col" className="px-5 py-3">Actor</th>
                    <th scope="col" className="px-5 py-3">Entity</th>
                    <th scope="col" className="px-5 py-3">Recorded</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {filteredLogs.map((log) => (
                    <tr key={log.id} className="transition-colors hover:bg-slate-50/70">
                      <td className="px-5 py-4">
                        <div className="flex items-center gap-3">
                          <ActivityMark action={log.action} />
                          <span className="font-medium text-slate-950">{toLabel(log.action)}</span>
                        </div>
                      </td>
                      <td className="px-5 py-4 text-slate-700">
                        <span className="flex items-center gap-2">
                          {log.actor_email ? (
                            <UserRound className="h-4 w-4 text-slate-400" aria-hidden="true" />
                          ) : (
                            <Bot className="h-4 w-4 text-slate-400" aria-hidden="true" />
                          )}
                          {log.actor_email ?? "System"}
                        </span>
                      </td>
                      <td className="px-5 py-4 text-slate-700">
                        {toLabel(log.entity_type)} {log.entity_id ? `#${log.entity_id.slice(0, 8)}` : ""}
                      </td>
                      <td className="px-5 py-4 text-slate-600">{formatDateTime(log.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
    </div>
  );
}

function ActivityMark({ action }: { action: string }) {
  const destructive = /delete|remove|purge|revoke/i.test(action);
  const positive = /create|confirm|approve|restore|save/i.test(action);
  return (
    <span
      className={
        destructive
          ? "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-red-50 text-red-700"
          : positive
            ? "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-700"
            : "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-700"
      }
    >
      {destructive ? (
        <ShieldCheck className="h-4 w-4" aria-hidden="true" />
      ) : (
        <Activity className="h-4 w-4" aria-hidden="true" />
      )}
    </span>
  );
}

function formatCompactTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Recorded";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function toLabel(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

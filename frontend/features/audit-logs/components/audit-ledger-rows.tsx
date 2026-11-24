import { Activity, Bot, ShieldCheck, UserRound } from "lucide-react";
import { Badge } from "@/components/ui";
import { formatDateTime } from "@/lib/utils/format";
import type { AuditLogListItem, AuditLogResult } from "@/features/operations/api/operations.api";
import { toLabel } from "../audit-filter-model";

export function AuditLedgerRows({ data, showAgency }: { data: AuditLogListItem[]; showAgency: boolean; }) {
  return (
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
              {showAgency ? <div className="col-span-2"><dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Tenant</dt><dd className="mt-1 break-all text-slate-800">{log.agency_id ?? "Global scope"}</dd></div> : null}
              <div className="col-span-2"><dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Recorded</dt><dd className="mt-1 text-slate-800">{formatDateTime(log.created_at)}</dd></div>
            </dl>
          </article>
        ))}
      </div>

      <div className="hidden overflow-x-auto md:block">
        <table className="w-full min-w-[900px] text-left text-sm">
          <caption className="sr-only">Audit log events</caption>
          <thead><tr className="border-b border-slate-200 bg-slate-50/70 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500"><th scope="col" className="px-5 py-3">Event</th><th scope="col" className="px-5 py-3">Actor</th><th scope="col" className="px-5 py-3">Entity</th>{showAgency ? <th scope="col" className="px-5 py-3">Tenant</th> : null}<th scope="col" className="px-5 py-3">Result</th><th scope="col" className="px-5 py-3">Recorded</th></tr></thead>
          <tbody className="divide-y divide-slate-100">
            {data.map((log) => (
              <tr key={log.id} className="transition-colors hover:bg-slate-50/70">
                <td className="px-5 py-4"><div className="flex items-center gap-3"><ActivityMark action={log.event_type} /><span className="font-medium text-slate-950">{toLabel(log.event_type)}</span></div></td>
                <td className="px-5 py-4 text-slate-700"><span className="flex items-center gap-2">{log.actor_email ? <UserRound className="h-4 w-4 text-slate-400" aria-hidden="true" /> : <Bot className="h-4 w-4 text-slate-400" aria-hidden="true" />}{log.actor_email ?? "System"}</span></td>
                <td className="max-w-64 break-all px-5 py-4 text-slate-700">{toLabel(log.entity_type)} {log.entity_id ? `#${log.entity_id}` : ""}</td>
                {showAgency ? <td className="max-w-64 break-all px-5 py-4 text-slate-700">{log.agency_id ?? "Global scope"}</td> : null}
                <td className="px-5 py-4"><ResultBadge result={log.result} /></td>
                <td className="px-5 py-4 text-slate-600">{formatDateTime(log.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function ResultBadge({ result }: { result: AuditLogResult | null; }) {
  const variant = result === "success" ? "success" : result === "blocked" || result === "denied" ? "warning" : result === "failed" ? "destructive" : "outline";
  return <Badge variant={variant}>{result ? toLabel(result) : "Unclassified"}</Badge>;
}

function ActivityMark({ action }: { action: string; }) {
  const destructive = /delete|remove|purge|revoke/i.test(action);
  const positive = /create|confirm|approve|restore|save/i.test(action);
  return (
    <span className={destructive ? "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-red-50 text-red-700" : positive ? "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-700" : "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-700"}>
      {destructive ? <ShieldCheck className="h-4 w-4" aria-hidden="true" /> : <Activity className="h-4 w-4" aria-hidden="true" />}
    </span>
  );
}


"use client";

import { ClipboardList } from "lucide-react";
import { EmptyState, PageHeader } from "@/components/shared";
import { Card, CardContent, Skeleton } from "@/components/ui";
import { formatDateTime } from "@/lib/utils/format";
import { useAuditLogs } from "@/features/operations/hooks/use-operations";

export default function AuditLogsPage() {
  const { data, isLoading, error } = useAuditLogs();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Audit Logs" description="Security and operational activity across your permitted scope." />
      {error && <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">Audit logs are unavailable for this account.</div>}
      {isLoading ? (
        <div className="grid gap-3">{Array.from({ length: 6 }).map((_, index) => <Skeleton key={index} className="h-16 w-full" />)}</div>
      ) : !data || data.length === 0 ? (
        <EmptyState icon={<ClipboardList className="h-5 w-5" />} title="No audit events" description="Operational events will appear here as users work." />
      ) : (
        <Card>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-100 text-xs uppercase tracking-wide text-slate-400">
                    <th className="px-5 py-4">Action</th>
                    <th className="px-5 py-4">Actor</th>
                    <th className="px-5 py-4">Entity</th>
                    <th className="px-5 py-4">Time</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {data.map((log) => (
                    <tr key={log.id}>
                      <td className="px-5 py-4 font-medium text-slate-900">{toLabel(log.action)}</td>
                      <td className="px-5 py-4 text-slate-600">{log.actor_email ?? "System"}</td>
                      <td className="px-5 py-4 text-slate-600">{toLabel(log.entity_type)} {log.entity_id ? `#${log.entity_id.slice(0, 8)}` : ""}</td>
                      <td className="px-5 py-4 text-slate-500">{formatDateTime(log.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function toLabel(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

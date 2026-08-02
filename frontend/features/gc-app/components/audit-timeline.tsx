import { Card, CardContent } from "@/components/ui";
import type { GcAuditEvent } from "../types";
import { formatGcDateTime } from "../utils";

export function AuditTimeline({ events }: { events: GcAuditEvent[] }) {
  return (
    <Card>
      <CardContent className="space-y-4 p-5">
        <div><h3 className="font-semibold text-slate-900">App-access audit history</h3><p className="mt-1 text-sm text-slate-500">Enablement, access, publication, revocation, and content actions for this group.</p></div>
        {events.length === 0 ? <p className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">No GC App audit events recorded.</p> : events.map((event) => (
          <div key={event.id} className="border-l-2 border-blue-200 py-1 pl-4">
            <p className="text-sm font-medium text-slate-800">{event.summary}</p>
            <p className="mt-1 text-xs text-slate-500">{event.actor_name ?? "System"} · {formatGcDateTime(event.created_at)}</p>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

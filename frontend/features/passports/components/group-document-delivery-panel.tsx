"use client";

import { AlertTriangle, CheckCircle2, Clock3, FileText, Send } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { Badge, buttonVariants, Card, CardContent, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { useDocumentDeliveryTracking } from "@/features/documents/hooks/use-document-distribution";
import { formatDateTime } from "@/lib/utils/format";
import { cn } from "@/lib/utils/cn";

export function GroupDocumentDeliveryPanel({ groupId }: { groupId: string }) {
  const tracking = useDocumentDeliveryTracking(groupId);

  if (tracking.isLoading) {
    return <Skeleton className="h-44 w-full rounded-2xl" />;
  }

  const counts = tracking.data?.counts;
  const successful = (counts?.sent ?? 0) + (counts?.delivered ?? 0) + (counts?.read ?? 0);
  const attention = (counts?.failed ?? 0) + (counts?.delivery_unknown ?? 0);
  const recent = tracking.data?.deliveries.slice(0, 6) ?? [];

  return (
    <Card>
      <CardContent className="space-y-4 p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-700">
              <Send className="h-5 w-5" aria-hidden="true" />
            </span>
            <div>
              <h2 className="text-base font-semibold text-slate-900">Document delivery tracking</h2>
              <p className="mt-1 text-sm text-slate-600">
                Visa, departure-ticket, and arrival-ticket WhatsApp delivery status for this group.
              </p>
            </div>
          </div>
          <Link
            href={ROUTES.dashboard.documentGroup(groupId) as never}
            className={cn(buttonVariants({ variant: "secondary", size: "sm" }), "shrink-0")}
          >
            <FileText className="h-4 w-4" aria-hidden="true" />
            Manage deliveries
          </Link>
        </div>

        {tracking.error ? (
          <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            Document delivery tracking could not be loaded.
          </div>
        ) : !counts?.total ? (
          <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-5 py-6 text-center">
            <div className="font-medium text-slate-800">No document broadcasts sent yet</div>
            <p className="mt-1 text-sm text-slate-500">
              Save a matched document list, then preview and send it from Document Distribution.
            </p>
          </div>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-4">
              <TrackingMetric label="Total" value={counts.total} icon={<FileText className="h-4 w-4" />} />
              <TrackingMetric label="Queued" value={counts.queued} icon={<Clock3 className="h-4 w-4" />} />
              <TrackingMetric label="Sent" value={successful} icon={<CheckCircle2 className="h-4 w-4" />} tone="success" />
              <TrackingMetric label="Needs attention" value={attention} icon={<AlertTriangle className="h-4 w-4" />} tone={attention ? "warning" : "neutral"} />
            </div>

            <div className="overflow-hidden rounded-xl border border-slate-200">
              <div className="divide-y divide-slate-100">
                {recent.map((delivery) => (
                  <div key={delivery.delivery_id} className="grid gap-2 px-4 py-3 text-sm sm:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_auto] sm:items-center">
                    <div className="min-w-0">
                      <div className="truncate font-semibold text-slate-900">{delivery.passenger_name}</div>
                      <div className="mt-0.5 truncate text-xs text-slate-500">
                        {delivery.document_filename} · {delivery.phone_number}
                      </div>
                    </div>
                    <div className="text-xs text-slate-500">
                      {documentLabel(delivery.document_type)} · {formatDateTime(delivery.status_updated_at)}
                    </div>
                    <DeliveryTrackingBadge status={delivery.status} />
                    {delivery.error_message && delivery.status === "failed" && (
                      <div className="text-xs text-red-700 sm:col-span-3">{delivery.error_message}</div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function TrackingMetric({
  label,
  value,
  icon,
  tone = "neutral",
}: {
  label: string;
  value: number;
  icon: ReactNode;
  tone?: "neutral" | "success" | "warning";
}) {
  const color = tone === "success"
    ? "border-emerald-200 bg-emerald-50 text-emerald-900"
    : tone === "warning"
      ? "border-amber-200 bg-amber-50 text-amber-900"
      : "border-slate-200 bg-slate-50 text-slate-800";
  return (
    <div className={`rounded-xl border px-3 py-3 ${color}`}>
      <div className="flex items-center gap-2 text-xs font-medium opacity-75">{icon}{label}</div>
      <div className="mt-1 text-xl font-semibold">{value}</div>
    </div>
  );
}

function DeliveryTrackingBadge({ status }: { status: string }) {
  if (status === "read") return <Badge variant="success">Read</Badge>;
  if (status === "delivered") return <Badge variant="success">Delivered</Badge>;
  if (status === "submitted" || status === "sent") return <Badge variant="success">Sent</Badge>;
  if (status === "failed") return <Badge variant="destructive">Failed</Badge>;
  if (status === "delivery_unknown") return <Badge variant="warning">Outcome unknown</Badge>;
  return <Badge variant="outline">Queued</Badge>;
}

function documentLabel(documentType: string): string {
  if (documentType === "visa") return "Visa";
  if (documentType === "flight_ticket") return "Departure Ticket";
  if (documentType === "flight_ticket_arrival") return "Arrival Ticket";
  return "Travel Document";
}

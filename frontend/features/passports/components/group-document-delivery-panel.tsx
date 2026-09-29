"use client";

import { ChevronDown, FileText, Send } from "lucide-react";
import Link from "next/link";
import { Badge, buttonVariants, Card, CardContent, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { distributionDocumentLabel } from "@/features/documents/config/document-distribution-lanes";
import { useDocumentDeliveryTracking } from "@/features/documents/hooks/use-document-distribution";
import { formatDateTime } from "@/lib/utils/format";
import { cn } from "@/lib/utils/cn";

export function GroupDocumentDeliveryPanel({ groupId }: { groupId: string }) {
  const tracking = useDocumentDeliveryTracking(groupId);

  if (tracking.isLoading) {
    return <Skeleton className="h-52 w-full rounded-xl" />;
  }

  const counts = tracking.data?.counts;
  const delivered = (counts?.delivered ?? 0) + (counts?.read ?? 0);
  const recent = tracking.data?.deliveries.slice(0, 6) ?? [];

  return (
    <Card className="h-full min-w-0">
      <CardContent className="flex h-full min-h-52 flex-col gap-3 p-4">
        <div className="flex items-center gap-3">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
            <Send className="h-4 w-4" aria-hidden="true" />
          </span>
          <h2 className="text-sm font-semibold text-slate-900">Document deliveries</h2>
        </div>

        <div className="min-w-0 flex-1">
          {tracking.error ? (
            <p role="alert" className="text-sm text-red-700">
              Document delivery tracking could not be loaded.
            </p>
          ) : !counts?.total ? (
            <>
              <p className="text-sm font-medium text-slate-800">No document broadcasts sent yet</p>
              <p className="mt-1 text-xs leading-5 text-slate-500">
                Prepare and send visas and tickets from Document Distribution.
              </p>
            </>
          ) : (
            <>
              <p className="text-base font-semibold text-slate-900">
                {delivered.toLocaleString()} of {counts.total.toLocaleString()} delivered
              </p>
              <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
                <DeliveryCount label="Queued" value={counts.queued} />
                <DeliveryCount label="Awaiting delivery" value={counts.sent} />
                <DeliveryCount label="Failed" value={counts.failed} attention />
                <DeliveryCount label="Unknown" value={counts.delivery_unknown} attention />
              </dl>
            </>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-3">
          <Link
            href={ROUTES.dashboard.documentGroup(groupId)}
            className={cn(buttonVariants({ variant: "secondary", size: "sm" }), "shrink-0")}
          >
            <FileText className="h-4 w-4" aria-hidden="true" />
            Manage deliveries
          </Link>
        </div>

        {!tracking.error && recent.length > 0 && (
          <details className="group/recent border-t border-slate-100 pt-2">
            <summary className="flex min-h-9 cursor-pointer list-none items-center justify-between gap-2 rounded-md text-xs font-medium text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 [&::-webkit-details-marker]:hidden">
              Recent delivery updates
              <ChevronDown className="h-4 w-4 shrink-0 transition-transform group-open/recent:rotate-180" aria-hidden="true" />
            </summary>
            <ul aria-label="Recent document deliveries" className="mt-2 max-h-64 space-y-3 overflow-y-auto overscroll-contain pr-1">
              {recent.map((delivery) => (
                <li key={delivery.delivery_id} className="min-w-0 border-t border-slate-100 pt-3 first:border-t-0 first:pt-0">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="min-w-0 break-words text-sm font-medium text-slate-900">{delivery.passenger_name}</span>
                    <DeliveryTrackingBadge status={delivery.status} />
                  </div>
                  <p className="mt-1 break-words text-xs text-slate-500">
                    {delivery.document_filename} · {delivery.phone_number}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    {distributionDocumentLabel(delivery.document_type)} · {formatDateTime(delivery.status_updated_at)}
                  </p>
                  {delivery.error_message && delivery.status === "failed" && (
                    <p className="mt-1 break-words text-xs text-red-700">{delivery.error_message}</p>
                  )}
                </li>
              ))}
            </ul>
          </details>
        )}
      </CardContent>
    </Card>
  );
}

function DeliveryCount({ label, value, attention = false }: { label: string; value: number; attention?: boolean }) {
  return (
    <div className={cn("flex items-baseline gap-1", attention && value > 0 && "text-red-700")}>
      <dt>{label}</dt>
      <dd className="font-semibold tabular-nums">{value.toLocaleString()}</dd>
    </div>
  );
}

function DeliveryTrackingBadge({ status }: { status: string }) {
  if (status === "read") return <Badge variant="success">Read</Badge>;
  if (status === "delivered") return <Badge variant="success">Delivered</Badge>;
  if (status === "submitted") return <Badge variant="outline">Accepted by WhatsApp</Badge>;
  if (status === "sent") return <Badge variant="outline">Sent</Badge>;
  if (status === "failed") return <Badge variant="destructive">Failed</Badge>;
  if (status === "delivery_unknown") return <Badge variant="warning">Outcome unknown</Badge>;
  if (status === "processing") return <Badge variant="outline">Processing</Badge>;
  if (status === "queued") return <Badge variant="outline">Queued</Badge>;
  return <Badge variant="warning">Status unavailable</Badge>;
}

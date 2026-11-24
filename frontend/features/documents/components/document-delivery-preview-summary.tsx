import type { DocumentDeliveryPreview } from "@/types/document-distribution.types";
import { distributionDocumentLabel } from "../config/document-distribution-lanes";

type DeliveryPreviewSummaryProps = {
  preview: DocumentDeliveryPreview;
  assignedDocumentCount: number;
  refreshing: boolean;
  deliveryIssues: readonly {
    label: string;
    count: number;
  }[];
};

export function DocumentDeliveryPreviewSummary({
  preview,
  assignedDocumentCount,
  refreshing,
  deliveryIssues,
}: DeliveryPreviewSummaryProps) {
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-slate-600">
        <p><span className="font-semibold text-slate-900">
          {distributionDocumentLabel(preview.document_type)}
        </span> · {assignedDocumentCount.toLocaleString()} assigned {assignedDocumentCount === 1 ? "document" : "documents"}</p>
        {refreshing && <p role="status" className="text-blue-700">Refreshing documents and recipient details…</p>}
      </div>
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <DeliverySummary label="Assigned travellers" value={preview.summary.total_passengers} />
        <DeliverySummary label="Ready" value={preview.summary.ready} tone="success" />
        <DeliverySummary label="Retryable" value={preview.summary.retryable} tone="warning" />
        <DeliverySummary label="Already sent" value={preview.summary.already_sent} />
        <DeliverySummary label="In progress" value={preview.summary.in_progress} />
        <DeliverySummary label="Blocked" value={preview.summary.blocked} tone="danger" />
      </div>

      {Boolean(preview.summary.excluded_without_document) && (
        <p className="rounded-xl bg-slate-50 px-4 py-3 text-sm leading-6 text-slate-600">
          {preview.summary.excluded_without_document?.toLocaleString()} {preview.summary.excluded_without_document === 1 ? "traveller has" : "travellers have"} no assigned PDF in this section and {preview.summary.excluded_without_document === 1 ? "is" : "are"} not included in this send preview.
        </p>
      )}

      {deliveryIssues.length > 0 && (
        <dl aria-label="Delivery issues" className="flex flex-wrap gap-x-5 gap-y-2 text-sm text-amber-900">
          {deliveryIssues.map((issue) => (
            <div key={issue.label} className="flex items-baseline gap-2">
              <dt>
                {issue.label}
              </dt>
              <dd className="font-semibold tabular-nums">
                {issue.count.toLocaleString()}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {preview.configuration_error && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          {preview.configuration_error}
        </div>
      )}

      {preview.can_send && !preview.preview_token && (
        <p
          role="alert"
          className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
        >
          Refresh the preview to check the latest document recipients before sending.
        </p>
      )}

    </>
  );
}

type DeliverySummaryProps = {
  label: string;
  value: number;
  tone?: "neutral" | "success" | "warning" | "danger";
};

function DeliverySummary({
  label,
  value,
  tone = "neutral"
}: DeliverySummaryProps) {
  const toneClass = tone === "success"
    ? "border-emerald-200 bg-emerald-50 text-emerald-900"
    : tone === "warning"
      ? "border-amber-200 bg-amber-50 text-amber-900"
      : tone === "danger"
        ? "border-red-200 bg-red-50 text-red-900"
        : "border-slate-200 bg-slate-50 text-slate-900";
  return (
    <div className={`rounded-xl border p-3 ${toneClass}`}>
      <div className="text-xs font-medium opacity-70">
        {label}
      </div>
      <div className="mt-1 text-xl font-semibold">
        {value}
      </div>
    </div>
  );
}

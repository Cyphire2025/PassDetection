"use client";

import type { DocumentUpdateRecipient } from "../api/document-updates.api";

const STATUS_LABELS: Record<string, string> = {
  queued: "Queued", processing: "Sending", submitted: "Accepted by WhatsApp",
  sent: "Sent", delivered: "Delivered", read: "Read", failed: "Failed",
  delivery_unknown: "Outcome unknown", skipped: "Skipped",
};

export function hasPendingDocumentUpdates(rows: DocumentUpdateRecipient[] = []) {
  return rows.some(row => ["queued", "processing", "submitted", "sent"].includes(row.latest_update_status ?? ""));
}

export function DocumentUpdateStatus({ recipient }: { recipient: DocumentUpdateRecipient }) {
  if (!recipient.latest_update_status) return null;
  const needsAttention = ["failed", "delivery_unknown"].includes(recipient.latest_update_status);
  return <span className="block space-y-1 text-sm">
    <span className={`block font-medium ${needsAttention ? "text-amber-800" : "text-slate-700"}`}>Latest update: {STATUS_LABELS[recipient.latest_update_status] ?? recipient.latest_update_status.replaceAll("_", " ")}</span>
    {recipient.latest_update_at && <time dateTime={recipient.latest_update_at} className="block text-xs text-slate-500">{new Date(recipient.latest_update_at).toLocaleString()}</time>}
    {recipient.latest_update_error && <span className="block break-words text-amber-800">{recipient.latest_update_error}</span>}
  </span>;
}

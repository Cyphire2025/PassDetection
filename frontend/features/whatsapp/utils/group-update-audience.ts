import type { GroupUpdateAudience, GroupUpdateRecipient } from "../api/group-updates.api";

export const UPDATE_ACCEPTED = new Set(["submitted", "sent", "delivered", "read"]);
export const UPDATE_ACTIVE = new Set(["queued", "processing"]);

export function documentsSent(row: GroupUpdateRecipient) {
  return row.document_count > 0 && row.document_count === row.confirmed_count;
}

export function updateAudienceMatches(row: GroupUpdateRecipient, audience: GroupUpdateAudience) {
  return (audience.submission_status === "all" || row.submission_status === audience.submission_status)
    && (audience.document_status === "all" || (audience.document_status === "sent") === documentsSent(row));
}

export function updateStatusLabel(status: string | null | undefined) {
  const labels: Record<string, string> = { not_sent: "Not sent", queued: "Queued", processing: "Sending", submitted: "Submitted to WhatsApp", sent: "Sent", delivered: "Delivered", read: "Read", failed: "Failed", delivery_unknown: "Outcome unknown", skipped: "Skipped", cancelled: "Cancelled" };
  return status ? labels[status] ?? status.replaceAll("_", " ") : "Not sent";
}

export function updateAudienceSummary(audience: GroupUpdateAudience, documentLabel: string) {
  const submission = audience.submission_status === "submitted" ? "Submitted travellers" : audience.submission_status === "not_submitted" ? "Travellers who have not submitted" : "All travellers";
  return `${submission} · ${audience.document_status === "all" ? "Any document distribution status" : `${documentLabel}: ${audience.document_status === "sent" ? "sent" : "pending"}`}`;
}

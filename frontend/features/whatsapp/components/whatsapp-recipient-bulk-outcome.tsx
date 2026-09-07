"use client";

import type { WhatsAppBulkResendResponse, WhatsAppRecipient } from "../api/whatsapp.api";

const OUTCOME_LABELS: Record<string, string> = {
  skipped_replaced: "Skipped: this person has been replaced in the linked passport group.",
  skipped_in_progress: "Skipped: a message of this type is already in progress.",
  skipped_delivery_unknown: "Skipped: verify the previous delivery before resending.",
  skipped_no_saved_message: "Skipped: no saved message was available. Send an initial message first.",
  skipped_ineligible: "Skipped: the current delivery status does not allow a resend.",
  failed: "Could not queue or send this message. Check the delivery activity for details.",
  delivery_unknown: "Delivery is uncertain. Verify it before sending another message.",
  stalled: "Delivery has stalled. Verify the delivery activity before sending again.",
};

export function RecipientBulkOutcome({ response, recipients, onDismiss }: {
  response: WhatsAppBulkResendResponse;
  recipients: WhatsAppRecipient[];
  onDismiss: () => void;
}) {
  const exceptions = response.results.filter((item) => item.status in OUTCOME_LABELS);
  if (!exceptions.length) return null;
  const names = new Map(recipients.map((recipient) => [recipient.id, recipient.name]));
  return (
    <details className="mb-4 rounded-xl border border-amber-200 bg-amber-50/50 px-4 py-3">
      <summary className="cursor-pointer text-sm font-semibold text-amber-900">
        Last resend: {exceptions.length} {exceptions.length === 1 ? "recipient needs" : "recipients need"} attention
      </summary>
      <p className="mt-2 text-xs leading-relaxed text-slate-600">These are the results returned when you submitted the resend. Ongoing delivery updates appear in the broadcast activity.</p>
      <ul aria-label="Resend results needing attention" className="mt-3 max-h-60 divide-y divide-amber-100 overflow-y-auto">
        {exceptions.map((item) => (
          <li key={item.recipient_id} className="py-2.5 text-xs">
            <p className="font-semibold text-slate-800">{names.get(item.recipient_id) || item.phone_number || "Recipient"}</p>
            <p className="mt-1 leading-relaxed text-slate-600">{OUTCOME_LABELS[item.status]}</p>
          </li>
        ))}
      </ul>
      <button type="button" onClick={onDismiss} className="mt-3 rounded text-xs font-semibold text-slate-600 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500">Dismiss result details</button>
    </details>
  );
}

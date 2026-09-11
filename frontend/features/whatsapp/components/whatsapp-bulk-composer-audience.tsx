"use client";

import type { WhatsAppBulkResendPreviewResponse, WhatsAppRecipient } from "../api/whatsapp.api";
import { getBulkResendEligibility, summarizeBulkResend } from "../utils/recipient-bulk-selection";
import { welcomeDeliveryBlockReason } from "../utils/recipient-delivery";

const ELIGIBILITY_LABELS = {
  eligible: "Ready to resend",
  no_saved_message: "No saved message",
  in_progress: "Already in progress",
  delivery_unknown: "Delivery needs review",
  blocked: "Needs review",
} as const;

export function RecipientBulkComposerAudience({ recipients, messageType, hiddenCount, preview }: {
  recipients: WhatsAppRecipient[];
  messageType: "welcome" | "passport_link";
  hiddenCount: number;
  preview: WhatsAppBulkResendPreviewResponse | null;
}) {
  const estimate = summarizeBulkResend(recipients, messageType);
  const locallyAllowedIds = new Set(recipients.filter((recipient) => !welcomeDeliveryBlockReason(recipient, messageType)).map((recipient) => recipient.id));
  const readyIds = preview ? new Set(preview.eligible_recipient_ids.filter((id) => locallyAllowedIds.has(id))) : null;
  const readyCount = readyIds?.size ?? estimate.eligible;
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
        <div><p className="text-lg font-semibold tabular-nums text-slate-900">{recipients.length}</p><p className="mt-0.5 text-xs text-slate-500">Selected</p></div>
        <div><p className="text-lg font-semibold tabular-nums text-blue-700">{readyCount}</p><p className="mt-0.5 text-xs text-slate-500">Ready to resend</p></div>
        <div><p className="text-lg font-semibold tabular-nums text-slate-500">{recipients.length - readyCount}</p><p className="mt-0.5 text-xs text-slate-500">Will be skipped</p></div>
      </div>
      <p className="text-xs leading-5 text-slate-600">{messageType === "welcome" ? "Only failed welcome attempts can be retried. Numbers already welcomed or awaiting delivery are skipped." : "This will send another message, including to people who already received it, after confirmed welcome delivery."} Your recipient selection is fixed here; go back to the list to change it.</p>
      {hiddenCount > 0 && <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">Includes {hiddenCount} selected {hiddenCount === 1 ? "person" : "people"} outside your previous search or filter.</p>}
      <details className="rounded-lg border border-slate-200">
        <summary className="cursor-pointer px-3 py-2.5 text-xs font-semibold text-slate-700">Review {recipients.length} selected recipients</summary>
        <ul aria-label="Selected resend recipients" className="max-h-48 divide-y divide-slate-100 overflow-y-auto border-t border-slate-100">
          {recipients.map((recipient) => {
            const estimated = getBulkResendEligibility(recipient, messageType);
            const ready = readyIds ? readyIds.has(recipient.id) : estimated === "eligible";
            return <li key={recipient.id} className="flex items-center justify-between gap-3 px-3 py-2.5"><div className="min-w-0"><p className="truncate text-xs font-medium text-slate-800">{recipient.name || "Unnamed recipient"}</p><p className="mt-0.5 text-[11px] tabular-nums text-slate-500">{recipient.normalized_phone_number}</p>{!ready && welcomeDeliveryBlockReason(recipient, messageType) && <p className="mt-1 text-[11px] leading-4 text-amber-700">{welcomeDeliveryBlockReason(recipient, messageType)}</p>}</div><span className={`shrink-0 text-[11px] ${ready ? "text-blue-700" : "text-slate-500"}`}>{ready ? "Ready to resend" : estimated === "eligible" ? "Unavailable saved message" : ELIGIBILITY_LABELS[estimated]}</span></li>;
          })}
        </ul>
      </details>
      <p className="text-xs leading-5 text-slate-400">Sends already in progress, uncertain delivery and unavailable saved messages are skipped. Availability is checked again before queuing.</p>
    </div>
  );
}

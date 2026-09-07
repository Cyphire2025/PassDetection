"use client";

import { RotateCw } from "lucide-react";
import { Button } from "@/components/ui";
import type { WhatsAppRecipient } from "../api/whatsapp.api";
import { getBulkResendEligibility, summarizeBulkResend } from "../utils/recipient-bulk-selection";
import { DialogFrame, ErrorBanner } from "./whatsapp-dialog-ui";

const ELIGIBILITY_LABELS = {
  eligible: "Ready to resend",
  no_saved_message: "No saved message",
  in_progress: "Already in progress",
  delivery_unknown: "Delivery needs review",
  blocked: "Needs review",
} as const;

export function RecipientBulkReview({ messageType, recipients, hiddenCount, isSending, error, onClose, onConfirm }: {
  messageType: "welcome" | "passport_link";
  recipients: WhatsAppRecipient[];
  hiddenCount: number;
  isSending: boolean;
  error: string | null;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const summary = summarizeBulkResend(recipients, messageType);
  const skipped = summary.selected - summary.eligible;
  const label = messageType === "welcome" ? "welcome message" : "passport link";
  return (
    <DialogFrame title={`Resend ${label}?`} eyebrow="Review selected recipients" description="This will send another WhatsApp message, including to people who already received it." onClose={onClose} isBusy={isSending} layout="composer" widthClass="max-w-2xl">
      <div className="min-h-0 overflow-y-auto p-5 sm:p-7">
        <div className="grid grid-cols-3 gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div><p className="text-xl font-semibold tabular-nums text-slate-900">{summary.selected}</p><p className="mt-1 text-xs text-slate-500">Selected</p></div>
          <div><p className="text-xl font-semibold tabular-nums text-blue-700">{summary.eligible}</p><p className="mt-1 text-xs text-slate-500">Ready to resend</p></div>
          <div><p className="text-xl font-semibold tabular-nums text-slate-500">{skipped}</p><p className="mt-1 text-xs text-slate-500">Will be skipped</p></div>
        </div>
        <p className="mt-4 text-sm leading-relaxed text-slate-600">Each person receives their own previously saved {label}{messageType === "passport_link" ? ", with their personal passport link" : ""}. Existing sends in progress, uncertain delivery and missing saved messages are skipped.</p>
        {hiddenCount > 0 && <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">Includes {hiddenCount} selected {hiddenCount === 1 ? "person" : "people"} outside your current search or filter.</p>}
        <ul aria-label="Recipients included in resend review" className="mt-4 max-h-64 divide-y divide-slate-100 overflow-y-auto rounded-xl border border-slate-200">
          {recipients.map((recipient) => {
            const eligibility = getBulkResendEligibility(recipient, messageType);
            return <li key={recipient.id} className="flex items-center justify-between gap-4 px-4 py-3"><div className="min-w-0"><p className="truncate text-sm font-medium text-slate-800">{recipient.name || "Unnamed recipient"}</p><p className="mt-0.5 text-xs tabular-nums text-slate-500">{recipient.normalized_phone_number}</p></div><span className={`shrink-0 text-xs ${eligibility === "eligible" ? "text-blue-700" : "text-slate-500"}`}>{ELIGIBILITY_LABELS[eligibility]}</span></li>;
          })}
        </ul>
        <p className="mt-3 text-xs leading-relaxed text-slate-400">Counts are based on the latest loaded statuses. Availability is checked again before queuing.</p>
        {error && <div className="mt-4"><ErrorBanner message={error} /></div>}
      </div>
      <div className="flex shrink-0 flex-wrap justify-end gap-3 border-t border-slate-200 bg-white px-5 py-4 sm:px-7">
        <Button type="button" variant="secondary" onClick={onClose} disabled={isSending}>Back to recipients</Button>
        <Button type="button" onClick={onConfirm} isLoading={isSending} disabled={summary.eligible === 0 && !error}><RotateCw className="h-4 w-4" />Confirm resend</Button>
      </div>
    </DialogFrame>
  );
}

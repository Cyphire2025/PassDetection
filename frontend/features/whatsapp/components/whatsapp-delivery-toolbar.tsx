"use client";

import { RotateCw } from "lucide-react";
import { Button } from "@/components/ui";
import { formatMessageType } from "../utils/message-types";
import type { WhatsAppRecipientRosterTab } from "../utils/recipient-roster";

export const DELIVERY_FILTERS: ReadonlyArray<{ id: WhatsAppRecipientRosterTab; label: string }> = [
  { id: "all", label: "All" },
  { id: "ready", label: "Ready" },
  { id: "not_sent", label: "Not sent" },
  { id: "sent", label: "Sent" },
  { id: "failed", label: "Failed" },
  { id: "in_progress", label: "In progress" },
  { id: "needs_review", label: "Needs review" },
  { id: "shared", label: "Shared numbers" },
];

const CONTACT_FILTERS = [
  { id: "rejected", label: "Rejected imports" },
  { id: "unidentified", label: "Unidentified uploads" },
  { id: "replaced", label: "Replaced contacts" },
] as const;

export function DeliveryToolbar({ messageTypes, messageType, onMessageTypeChange, filter, onFilterChange, counts, disabled, refreshing, onRefresh }: {
  messageTypes: string[];
  messageType: string;
  onMessageTypeChange: (type: string) => void;
  filter: WhatsAppRecipientRosterTab;
  onFilterChange: (filter: WhatsAppRecipientRosterTab) => void;
  counts: Record<WhatsAppRecipientRosterTab, number>;
  disabled: boolean;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  const contactFilter = CONTACT_FILTERS.some(({ id }) => id === filter);
  return <div className="space-y-4">
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h3 className="text-lg font-semibold text-slate-900">Message delivery</h3>
        <p className="mt-1 text-sm text-slate-500">Choose a message to review its audience and delivery status.</p>
      </div>
      <Button type="button" variant="secondary" size="sm" disabled={refreshing || disabled} onClick={onRefresh} className="gap-2"><RotateCw aria-hidden="true" className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />Refresh status</Button>
    </div>
    <div className="grid gap-4 rounded-xl border border-slate-200 bg-slate-50/80 p-4 sm:grid-cols-[minmax(220px,320px)_1fr] sm:items-center">
      <label className="block text-xs font-semibold text-slate-600">Message type
        <select value={messageType} disabled={disabled} onChange={(event) => onMessageTypeChange(event.target.value)} className="mt-2 block h-11 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm font-semibold text-slate-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100 disabled:opacity-50">
          {messageTypes.map((type) => <option key={type} value={type}>{formatMessageType(type)}</option>)}
        </select>
      </label>
      <div className="text-xs leading-5 text-slate-500">
        <p>Filters and delivery statuses below apply to <strong className="font-semibold text-slate-700">{formatMessageType(messageType).toLowerCase()}</strong> only.</p>
        {messageType === "group_invite" && <p className="mt-1">Previously sent invites are excluded from retries, including when the template changes.</p>}
      </div>
    </div>
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Recipient delivery filters">
      {DELIVERY_FILTERS.map(({ id, label }) => <button key={id} type="button" aria-pressed={filter === id} disabled={disabled} onClick={() => onFilterChange(id)} className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:opacity-50 ${filter === id ? "border-blue-600 bg-blue-600 text-white" : "border-slate-200 bg-white text-slate-600 hover:border-blue-200 hover:bg-blue-50"}`}>
        {label}<span className={`rounded px-1.5 py-0.5 tabular-nums ${filter === id ? "bg-white/20" : "bg-slate-100 text-slate-500"}`}>{counts[id].toLocaleString()}</span>
      </button>)}
      <label className="sm:ml-auto"><span className="sr-only">Contact records requiring attention</span><select aria-label="Contact records requiring attention" value={contactFilter ? filter : ""} disabled={disabled} onChange={(event) => onFilterChange((event.target.value || "all") as WhatsAppRecipientRosterTab)} className={`h-9 max-w-full rounded-lg border bg-white px-2 text-xs ${contactFilter ? "border-amber-400 text-amber-800" : "border-slate-200 text-slate-600"}`}>
        <option value="">Contact records</option>
        {CONTACT_FILTERS.map(({ id, label }) => <option key={id} value={id}>{label} ({counts[id]})</option>)}
      </select></label>
    </div>
  </div>;
}

export function DeliverySelectionBar({ selectedCount, hiddenCount, messageType, disabled, onClear, onReview }: {
  selectedCount: number;
  hiddenCount: number;
  messageType: string;
  disabled: boolean;
  onClear: () => void;
  onReview: (type: "welcome" | "passport_link" | "group_invite") => void;
}) {
  const resendType = messageType === "welcome" || messageType === "passport_link" || messageType === "group_invite" ? messageType : null;
  return <section aria-label="Selected recipient actions" className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-white px-4 py-3 sm:px-7">
    <div className="min-w-0 text-xs text-slate-500" aria-live="polite">
      <p className="font-semibold text-slate-800">{selectedCount ? `${selectedCount.toLocaleString()} delivery numbers selected` : "Select delivery numbers to review a send"}</p>
      {hiddenCount > 0 && <p className="mt-1 text-amber-700">{hiddenCount} selected outside this filter. They remain included.</p>}
      {messageType === "group_invite" && <p className="mt-1">Only failed, previously unsuccessful invites can be retried.</p>}
      {resendType && <p className="mt-1">These actions use saved messages. For a first send, use Send {formatMessageType(messageType).toLowerCase()} in the broadcast menu.</p>}
      {!resendType && <p className="mt-1">Use each recipient’s actions to retry, or send a new {formatMessageType(messageType).toLowerCase()} from the broadcast menu.</p>}
    </div>
    <div className="flex items-center gap-3">
      {selectedCount > 0 && <button type="button" disabled={disabled} onClick={onClear} className="text-xs font-semibold text-slate-500 hover:text-slate-900 disabled:opacity-50">Clear selection</button>}
      {resendType && <Button type="button" disabled={!selectedCount || disabled} onClick={() => onReview(resendType)} className="gap-2"><RotateCw aria-hidden="true" className="h-4 w-4" />{messageType === "passport_link" ? "Review resend" : "Review retry"}</Button>}
    </div>
  </section>;
}

"use client";

import { ArrowLeft, ArrowRight, Inbox, Search } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui";

export const fieldClass =
  "h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50 disabled:text-slate-400";
export const tableClass =
  "w-full text-left text-sm [&_thead]:bg-slate-50/80 [&_th]:px-5 [&_th]:py-3 [&_th]:text-xs [&_th]:font-medium [&_th]:text-slate-500 [&_td]:px-5 [&_td]:py-4 [&_tbody_tr]:border-t [&_tbody_tr]:border-slate-100 [&_tbody_tr]:transition-colors [&_tbody_tr:hover]:bg-slate-50/60";

export function WorkspaceSearch({
  value,
  onChange,
  placeholder,
  label = "Search",
  children,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  label?: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <label className="relative min-w-48 flex-1 sm:max-w-md">
        <span className="sr-only">{label}</span>
        <Search
          aria-hidden="true"
          className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-slate-400"
        />
        <input
          type="search"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          className={`${fieldClass} pl-10`}
        />
      </label>
      {children}
    </div>
  );
}

export function EmptyWorkspace({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center px-6 py-16 text-center">
      <span className="mb-4 rounded-xl bg-slate-50 p-3 text-slate-400">
        <Inbox className="h-6 w-6" aria-hidden="true" />
      </span>
      <h3 className="text-base font-semibold text-slate-900">{title}</h3>
      <p className="mt-2 max-w-md text-sm leading-6 text-slate-500">
        {description}
      </p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function WorkspacePagination({
  total,
  offset,
  limit,
  onChange,
  busy = false,
  label = "Results",
}: {
  total: number;
  offset: number;
  limit: number;
  onChange: (offset: number) => void;
  busy?: boolean;
  label?: string;
}) {
  return (
    <nav
      aria-label={`${label} pagination`}
      className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-5 py-3"
    >
      <p aria-live="polite" className="text-xs tabular-nums text-slate-500">
        {total === 0
          ? "0 results"
          : `${offset + 1}–${Math.min(offset + limit, total)} of ${total.toLocaleString()}`}
      </p>
      <div className="flex gap-2">
        <Button
          variant="ghost"
          disabled={busy || offset === 0}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Previous
        </Button>
        <Button
          variant="ghost"
          disabled={busy || offset + limit >= total}
          onClick={() => onChange(offset + limit)}
        >
          Next
          <ArrowRight className="h-3.5 w-3.5" />
        </Button>
      </div>
    </nav>
  );
}

const STATUS_LABELS: Record<string, string> = {
  submitted: "Sent",
  sent: "Sent",
  delivered: "Delivered",
  read: "Read",
  queued: "Queued",
  processing: "Sending",
  not_sent: "Not sent",
  failed: "Failed",
  delivery_unknown: "Unconfirmed",
  stalled: "Unconfirmed",
  cancelled: "Cancelled",
  dry_run: "Not sent",
};

export function DeliveryBadge({ status }: { status: string }) {
  const color = ["delivered", "read"].includes(status)
    ? "bg-emerald-50 text-emerald-700"
    : status === "failed" || status === "cancelled"
      ? "bg-red-50 text-red-700"
      : ["delivery_unknown", "stalled"].includes(status)
        ? "bg-amber-50 text-amber-800"
        : ["submitted", "sent", "queued", "processing"].includes(status)
          ? "bg-blue-50 text-blue-700"
          : "bg-slate-100 text-slate-600";
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-2 py-1 text-xs font-medium ${color}`}
    >
      <span
        className="h-1.5 w-1.5 rounded-full bg-current"
        aria-hidden="true"
      />
      {STATUS_LABELS[status] ?? "Unconfirmed"}
    </span>
  );
}

export function workspaceDate(value: string) {
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

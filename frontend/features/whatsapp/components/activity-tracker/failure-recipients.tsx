"use client";

import { cn } from "@/lib/utils/cn";
import type { WhatsAppActivityFailure } from "../../api/whatsapp-activity.api";

export function FailureRecipients({
  failures,
  loading,
  error,
  variant,
  onRetry,
}: {
  failures: WhatsAppActivityFailure[] | undefined;
  loading: boolean;
  error: Error | null;
  variant: "inline" | "floating";
  onRetry: () => void;
}) {
  return (
    <div
      className={cn(
        "border-t border-red-100 bg-red-50/70",
        variant === "floating"
          ? "cursor-auto touch-pan-y select-text px-5 py-3"
          : "-mx-4 -mb-3 mt-3 px-5 py-3",
      )}
      data-whatsapp-activity-no-drag={variant === "floating" ? "" : undefined}
    >
      <p className="text-xs font-semibold uppercase tracking-wide text-red-800">
        Failed recipients
      </p>
      {loading ? (
        <p className="mt-2 text-xs text-red-700" role="status">
          Loading failed recipient names...
        </p>
      ) : error ? (
        <div className="mt-2 flex items-center justify-between gap-3 text-xs text-red-700">
          <span>Failed names could not be refreshed.</span>
          <button
            type="button"
            className="font-semibold underline"
            onClick={onRetry}
          >
            Try again
          </button>
        </div>
      ) : failures && failures.length > 0 ? (
        <ul className="mt-2 max-h-48 space-y-1.5 overflow-y-auto pr-1">
          {failures.map((failure, index) => (
            <li
              key={`${failure.phone_number}:${index}`}
              className="rounded-xl bg-white px-3 py-2 text-xs shadow-sm ring-1 ring-red-100"
            >
              <div className="flex min-w-0 items-baseline justify-between gap-3">
                <span className="truncate font-semibold text-slate-900">
                  {failure.recipient_name}
                </span>
                <span className="shrink-0 tabular-nums text-slate-500">
                  {failure.phone_number}
                </span>
              </div>
              {failure.error_message ? (
                <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-red-700">
                  {failure.error_message}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-xs text-red-700">
          No failed recipient details are available yet.
        </p>
      )}
    </div>
  );
}

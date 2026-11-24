"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, ChevronDown, LoaderCircle, RefreshCw, X } from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils/cn";
import { whatsappActivityApi } from "../../api/whatsapp-activity.api";
import { isTerminalWhatsAppBatchStatus, shouldRetryWhatsAppBatchStatus, whatsappBatchHttpStatus } from "../../utils/batch-polling";
import type { DisplayedWhatsAppActivity } from "../../utils/activity-tracking";
import { WhatsAppBroadcastMotion } from "../whatsapp-broadcast-motion";
import type { WhatsAppActivityTrackerValue } from "./context";
import { FailureRecipients } from "./failure-recipients";
import { describeWhatsAppActivity } from "./progress";

export function WhatsAppActivityRow({
  activity,
  variant,
  onDismiss,
}: {
  activity: DisplayedWhatsAppActivity;
  variant: "inline" | "floating";
  onDismiss: WhatsAppActivityTrackerValue["dismissActivity"];
}) {
  const [showFailures, setShowFailures] = useState(false);
  const failuresQuery = useQuery({
    queryKey: [
      "whatsapp",
      "activities",
      activity.kind,
      activity.activity_id,
      "failures",
    ],
    queryFn: ({ signal }) =>
      whatsappActivityApi.failures(activity.kind, activity.activity_id, signal),
    enabled: showFailures && activity.failed > 0,
    retry: (failureCount, error) => shouldRetryWhatsAppBatchStatus(failureCount, whatsappBatchHttpStatus(error)),
    refetchInterval: (query) => !isTerminalWhatsAppBatchStatus(whatsappBatchHttpStatus(query.state.error)) &&
      showFailures && activity.failed > 0 && activity.queued > 0
        ? 2_000
        : false,
  });
  const {
    isRunning,
    isAwaitingReceipt,
    needsAttention,
    delivered,
    outcomeLabel,
    pendingStatusLabel,
    completedCount,
    progressPercent,
    sourceHref,
    skipCount,
    hasExpandedContent,
  } = describeWhatsAppActivity(activity, showFailures);

  return (
    <article
      className={cn(
        "text-slate-950",
        variant === "floating"
          ? cn(
              // The scroll container clips outer shadows into a visible rectangle.
              "overflow-hidden border border-emerald-200 bg-emerald-50",
              hasExpandedContent ? "rounded-[2rem]" : "rounded-full",
            )
          : "bg-white px-4 py-3",
      )}
      aria-label={`${activity.title}: ${outcomeLabel}`}
    >
      <div
        className={cn(
          "flex min-w-0 items-center gap-3",
          variant === "floating" && "touch-none px-3 py-2.5",
        )}
      >
        {activity.kind === "broadcast" ? (
          <div
            className={cn(
              "shrink-0",
              variant === "floating"
                ? "w-[76px] sm:w-[90px]"
                : "w-[96px] sm:w-[132px]",
            )}
          >
            <WhatsAppBroadcastMotion
              compact
              messageType={activity.messageType}
              startedAt={activity.startedAt}
              state={
                activity.refresh_error
                  ? "reconnecting"
                  : isRunning
                    ? "sending"
                    : needsAttention
                      ? "attention"
                      : isAwaitingReceipt
                        ? "sending"
                        : activity.total > 0 && delivered === activity.total
                          ? "complete"
                          : "reconnecting"
              }
            />
          </div>
        ) : (
          <span
            className={cn(
              "flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
              isRunning || isAwaitingReceipt
                ? "bg-blue-100 text-blue-700"
                : activity.failed > 0 || activity.delivery_unknown > 0
                  ? "bg-amber-100 text-amber-700"
                  : "bg-emerald-100 text-emerald-700",
            )}
          >
            {isRunning || isAwaitingReceipt ? (
              <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : activity.failed > 0 || activity.delivery_unknown > 0 ? (
              <AlertTriangle className="h-4 w-4" aria-hidden="true" />
            ) : (
              <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
            )}
          </span>
        )}

        <div className="min-w-0 flex-1">
          <div className={cn(
            "flex min-w-0 items-center gap-2",
            activity.kind === "broadcast" && "flex-wrap gap-y-0.5",
          )}>
            <Link
              href={sourceHref}
              className="truncate text-sm font-semibold text-slate-950 hover:text-blue-700 hover:underline"
            >
              {activity.title}
            </Link>
            {activity.refresh_error ? (
              <span
                className="inline-flex shrink-0 items-center gap-1 text-[11px] font-medium text-amber-700"
                title="Live status is reconnecting"
              >
                <RefreshCw className="h-3 w-3" aria-hidden="true" />
                Reconnecting
              </span>
            ) : null}
          </div>
          <div className={cn(
            "mt-0.5 flex min-w-0 items-center gap-2 text-xs text-slate-500",
            activity.kind === "broadcast" && "flex-wrap gap-x-2 gap-y-0.5",
          )}>
            <span className="truncate">{activity.context_label}</span>
            <span aria-hidden="true">{"\u00b7"}</span>
            <span className="shrink-0 font-semibold tabular-nums text-slate-700">
              {outcomeLabel}
            </span>
          </div>
          {pendingStatusLabel ? (
            <p className="mt-1 text-[11px] leading-4 text-slate-600" aria-live="polite" aria-atomic="true">
              {pendingStatusLabel}
            </p>
          ) : null}
          <div
            className={cn(
              "mt-1.5 h-1.5 overflow-hidden rounded-full",
              variant === "floating" ? "bg-emerald-100" : "bg-slate-100",
            )}
            role="progressbar"
            aria-label={`${activity.title} progress`}
            aria-valuemin={0}
            aria-valuemax={activity.total}
            aria-valuenow={completedCount}
            aria-valuetext={`${completedCount} processed of ${activity.total}. ${outcomeLabel}. ${activity.failed} failed. ${activity.delivery_unknown} unknown.`}
          >
            <div
              className={cn(
                "h-full rounded-full transition-[width] duration-500 ease-out",
                activity.failed > 0 || activity.delivery_unknown > 0
                  ? "bg-amber-500"
                  : isRunning || isAwaitingReceipt
                    ? "bg-blue-600"
                    : "bg-emerald-500",
              )}
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </div>

        {activity.failed > 0 ? (
          <button
            type="button"
            className="inline-flex h-8 shrink-0 items-center gap-1 rounded-full px-2 text-xs font-semibold text-red-700 hover:bg-red-50"
            aria-expanded={showFailures}
            aria-label={`${showFailures ? "Hide" : "Show"} ${activity.failed} failed recipients`}
            onClick={() => setShowFailures((current) => !current)}
          >
            {activity.failed}
            <ChevronDown
              className={cn(
                "h-4 w-4 transition-transform",
                showFailures && "rotate-180",
              )}
              aria-hidden="true"
            />
          </button>
        ) : null}

        <button
          type="button"
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          aria-label={`Close ${activity.title} progress`}
          title="Hide until the next broadcast starts"
          onClick={() => onDismiss(activity.activity_id, activity.kind)}
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>

      {skipCount > 0 ? (
        <p
          className={cn(
            "text-[11px] leading-4 text-slate-500",
            variant === "floating"
              ? "touch-none px-14 pb-2"
              : "ml-11 mt-1",
          )}
        >
          {activity.skipped_already_sent > 0
            ? `${activity.skipped_already_sent} already sent. `
            : ""}
          {activity.skipped_in_progress > 0
            ? `${activity.skipped_in_progress} already in progress. `
            : ""}
          {activity.skipped_delivery_unknown > 0
            ? `${activity.skipped_delivery_unknown} need delivery review.`
            : ""}
        </p>
      ) : null}

      {activity.delivery_unknown > 0 ? (
        <p
          className={cn(
            "text-xs font-medium text-amber-700",
            variant === "floating"
              ? "touch-none px-14 pb-2"
              : "ml-11 mt-1",
          )}
        >
          {activity.delivery_unknown} delivery outcome
          {activity.delivery_unknown === 1 ? " is" : "s are"} unknown and need review.
        </p>
      ) : null}

      {showFailures && activity.failed > 0 ? (
        <FailureRecipients
          failures={failuresQuery.data}
          loading={failuresQuery.isLoading}
          error={failuresQuery.error}
          variant={variant}
          onRetry={() => void failuresQuery.refetch()}
        />
      ) : null}
    </article>
  );
}

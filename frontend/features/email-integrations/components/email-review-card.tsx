import Link from "next/link";
import { Check, Clock3, RefreshCw, Search, X } from "lucide-react";
import { Button, Card, CardContent } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { formatConfidence, formatDateTime } from "@/lib/utils/format";
import type { useResolveEmailReview } from "../hooks/use-email-integrations";
import type { EmailReviewAction, EmailReviewItem } from "../types";
import { formatEmailLabel } from "../utils/email-integrations";
import { Definition, EmailStatusBadge } from "./email-integrations-ui";

export type ActionConfirmation = {
  item: EmailReviewItem;
  action: "mark_unrelated" | "reject";
};

export function EmailReviewCard({ item, resolve, isBusy, onMatch, onConfirm, onResolve }: {
  item: EmailReviewItem;
  resolve: ReturnType<typeof useResolveEmailReview>;
  isBusy: boolean;
  onMatch: (item: EmailReviewItem) => void;
  onConfirm: (confirmation: ActionConfirmation) => void;
  onResolve: (item: EmailReviewItem, action: EmailReviewAction) => void;
}) {
  const canResolve = item.status === "open" || item.status === "deferred";
  const allowedActions = new Set(item.allowed_actions);
  return (
    <Card>
      <CardContent className="space-y-5 p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <EmailStatusBadge status={item.status} />
              <span className="text-xs font-medium text-slate-500">
                {formatEmailLabel(item.review_type)}
              </span>
            </div>
            <h2 className="mt-2 break-words text-base font-semibold text-slate-950">
              {item.subject || "No subject"}
            </h2>
            <p className="mt-1 break-all text-sm text-slate-600">
              From {item.sender_email}
            </p>
          </div>
          <Link
            href={ROUTES.dashboard.emailIntegrationMessage(
              item.email_message_id,
            )}
            className="shrink-0 text-sm font-medium text-blue-700 hover:text-blue-800 hover:underline"
          >
            View source email
          </Link>
        </div>

        <dl className="grid gap-4 rounded-lg bg-slate-50 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <Definition term="Received">
            {formatDateTime(item.received_at)}
          </Definition>
          <Definition term="Attachment or link">
            {item.artifact_name ?? formatEmailLabel(item.artifact_kind)}
          </Definition>
          <Definition term="Proposed match">
            {item.proposed_passenger_name
              ? `${item.proposed_passenger_name}${item.proposed_group_name ? ` — ${item.proposed_group_name}` : ""}`
              : item.proposed_group_name ?? "No confident match"}
          </Definition>
          <Definition term="Confidence">
            {formatConfidence(item.confidence)}
          </Definition>
        </dl>

        <div className="grid gap-4 lg:grid-cols-3">
          <EvidenceList
            title="Matching evidence"
            items={item.evidence}
            emptyText="No supporting evidence was recorded."
          />
          <EvidenceList
            title="Detected conflicts"
            items={item.conflicts}
            emptyText="No conflicts were detected."
            tone={item.conflicts.length > 0 ? "warning" : "neutral"}
          />
          <div className="rounded-lg border border-slate-200 p-4">
            <h3 className="text-sm font-semibold text-slate-900">
              Proposed action
            </h3>
            <p className="mt-2 text-sm text-slate-700">
              {formatEmailLabel(item.proposed_action)}
            </p>
          </div>
        </div>

        {canResolve && (
          <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-4">
            {allowedActions.has("approve") && (
              <Button
                type="button"
                size="sm"
                leftIcon={<Check className="h-3.5 w-3.5" aria-hidden="true" />}
                isLoading={isBusy && resolve.variables?.request.action === "approve"}
                disabled={resolve.isPending}
                onClick={() => onResolve(item, "approve")}
              >
                Approve suggestion
              </Button>
            )}
            {allowedActions.has("assign") && (
              <Button
                type="button"
                size="sm"
                variant="secondary"
                leftIcon={<Search className="h-3.5 w-3.5" aria-hidden="true" />}
                disabled={resolve.isPending}
                onClick={() => onMatch(item)}
              >
                Choose another match
              </Button>
            )}
            {allowedActions.has("retry") && (
              <Button
                type="button"
                size="sm"
                variant="secondary"
                leftIcon={<RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />}
                isLoading={isBusy && resolve.variables?.request.action === "retry"}
                disabled={resolve.isPending}
                onClick={() => onResolve(item, "retry")}
              >
                Retry processing
              </Button>
            )}
            {allowedActions.has("defer") && (
              <Button
                type="button"
                size="sm"
                variant="secondary"
                leftIcon={<Clock3 className="h-3.5 w-3.5" aria-hidden="true" />}
                isLoading={isBusy && resolve.variables?.request.action === "defer"}
                disabled={resolve.isPending}
                onClick={() => onResolve(item, "defer")}
              >
                Defer
              </Button>
            )}
            {allowedActions.has("mark_unrelated") && (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={resolve.isPending}
                onClick={() =>
                  onConfirm({ item, action: "mark_unrelated" })
                }
              >
                Mark unrelated
              </Button>
            )}
            {allowedActions.has("reject") && (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="text-red-700 hover:bg-red-50 hover:text-red-800"
                leftIcon={<X className="h-3.5 w-3.5" aria-hidden="true" />}
                disabled={resolve.isPending}
                onClick={() =>
                  onConfirm({ item, action: "reject" })
                }
              >
                Reject
              </Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function EvidenceList({
  title,
  items,
  emptyText,
  tone = "neutral",
}: {
  title: string;
  items: string[];
  emptyText: string;
  tone?: "neutral" | "warning";
}) {
  return (
    <div
      className={`rounded-lg border p-4 ${tone === "warning"
        ? "border-amber-200 bg-amber-50/60"
        : "border-slate-200"
        }`}
    >
      <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
      {items.length > 0 ? (
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">
          {items.map((item, index) => (
            <li key={`${item}-${index}`}>{item}</li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-slate-600">{emptyText}</p>
      )}
    </div>
  );
}
